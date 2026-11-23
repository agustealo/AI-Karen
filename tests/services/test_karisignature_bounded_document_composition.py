"""WS-04B1: prove the existing consent and bounded-content owners compose.

This is a non-activating regression. The production source authority, reader,
persisted-sample authority and analyzer are exercised together. Only the
external storage, current-consent issuance and PostgreSQL evidence are test
doubles; no new runtime registration or authorization implementation is made.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.runtime.prompt.karisignature_contract import (
    KariSignatureRequest,
)
from ai_karen_engine.services.artifact_writing_style_source_authority import (
    ArtifactWritingStyleContentReader,
    ArtifactWritingStyleSourceAuthority,
)
from ai_karen_engine.services.database.repositories.artifact_store import (
    Artifact,
    VerifiedArtifactText,
)
from ai_karen_engine.services.database.repositories.base import RepositoryResult
from ai_karen_engine.services.formatting.karisignature_persisted_sample_authority import (
    WritingStylePersistedSampleAuthority,
    _Evidence,
)
from ai_karen_engine.services.formatting.karisignature_sample_analysis import (
    KariSignatureSample,
    KariSignatureSampleAnalyzer,
)
from ai_karen_engine.services.writing_style_sample_provenance import (
    VerifiedWritingStyleSource,
)

pytestmark = pytest.mark.asyncio

_SOURCE_TEXT = (
    "These are the author's own words for a deliberate, narrowly scoped "
    "writing-style analysis. The sample contains a complete passage with "
    "enough words to exercise the existing heuristic without publishing a "
    "profile, granting a purpose, or treating document ownership as consent."
)


def _case():
    tenant, actor, profile, sample_id, artifact_id, receipt = (
        str(uuid.uuid4()) for _ in range(6)
    )
    digest = KariSignatureSample.content_digest(_SOURCE_TEXT)
    request = KariSignatureRequest(
        tenant_id=tenant,
        actor_id=actor,
        profile_id=profile,
        purpose="analyze_style",
        correlation_id="ws-04b1-composition",
    )
    sample = KariSignatureSample(
        tenant_id=tenant,
        actor_id=actor,
        profile_id=profile,
        sample_id=sample_id,
        source_ref=f"document:{artifact_id}",
        content=_SOURCE_TEXT,
        digest=digest,
    )
    artifact = Artifact(
        id=artifact_id,
        tenant_id=tenant,
        user_id=actor,
        kind="document",
        filename="authorized.md",
        mime_type="text/plain",
        size_bytes=len(_SOURCE_TEXT.encode("utf-8")),
        sha256=digest,
    )
    verified_text = VerifiedArtifactText(
        artifact_id=artifact_id,
        tenant_id=tenant,
        user_id=actor,
        filename=artifact.filename,
        mime_type=artifact.mime_type,
        sha256=digest,
        text=_SOURCE_TEXT,
    )
    consent = VerifiedWritingStyleSource(
        tenant_id=tenant,
        profile_id=profile,
        owner_actor_id=actor,
        source_id=artifact_id,
        source_type="document",
        author_actor_id=actor,
        consent_receipt_id=receipt,
        analysis_allowed=True,
        style_use_allowed=False,
        consent_expires_at=None,
    )
    store = SimpleNamespace(
        get_metadata=AsyncMock(return_value=RepositoryResult(
            success=True, data=artifact,
        )),
        read_owner_active_text_bounded=AsyncMock(return_value=RepositoryResult(
            success=True, data=verified_text,
        )),
        download=AsyncMock(side_effect=AssertionError(
            "unbounded download is not authorized",
        )),
        read_owner_active_code=AsyncMock(side_effect=AssertionError(
            "code read cannot substitute for bounded text read",
        )),
    )
    issuer = SimpleNamespace(
        verify_current=AsyncMock(return_value=consent),
    )
    evidence = _Evidence(
        author_actor_id=actor,
        consent_receipt_id=receipt,
        consent_expires_at=None,
    )

    class EvidenceBoundAuthority(WritingStylePersistedSampleAuthority):
        def __init__(self):
            super().__init__(
                source_authority=ArtifactWritingStyleSourceAuthority(
                    artifacts=store,
                    consent_issuer=issuer,
                ),
                content_reader=ArtifactWritingStyleContentReader(
                    artifacts=store,
                ),
            )
            self.evidence_reads = 0
            self.revoke_evidence_after_content = False

        async def _read_evidence(
            self, request, sample, source_type, source_id,
        ):
            self.evidence_reads += 1
            if self.revoke_evidence_after_content and self.evidence_reads > 1:
                return None
            return evidence

    authority = EvidenceBoundAuthority()
    return SimpleNamespace(
        request=request,
        sample=sample,
        store=store,
        issuer=issuer,
        verified_text=verified_text,
        authority=authority,
        analyzer=KariSignatureSampleAnalyzer(authority),
    )


async def test_document_proposal_requires_full_consent_evidence_and_bounded_read():
    case = _case()
    proposal = await case.analyzer.propose(
        request=case.request, sample=case.sample,
    )

    assert proposal.analysis_status == "heuristic_proposal_only"
    assert proposal.approved is False
    assert proposal.source_digest == case.sample.digest
    assert not hasattr(proposal, "content")
    assert not hasattr(proposal, "instructions")
    # The proposal is only released after the entire owner/consent/read
    # chain passes again following the heuristic.
    assert case.authority.evidence_reads == 4
    assert case.store.get_metadata.await_count == 8
    assert case.issuer.verify_current.await_count == 8
    assert case.store.read_owner_active_text_bounded.await_count == 2
    case.store.read_owner_active_text_bounded.assert_awaited_with(
        case.verified_text.artifact_id,
        case.request.tenant_id,
        case.request.actor_id,
        max_bytes=65536,
    )
    case.store.download.assert_not_awaited()
    case.store.read_owner_active_code.assert_not_awaited()


@pytest.mark.parametrize(
    "failure",
    [
        "storage_denied",
        "storage_exception",
        "foreign_tenant",
        "foreign_owner",
        "foreign_artifact",
        "unsafe_filename",
        "invalid_mime",
        "wrong_digest",
        "changed_bytes",
        "missing_consent",
        "evidence_revoked_during_read",
    ],
)
async def test_document_composition_denies_untrusted_source_or_revocation(failure):
    case = _case()
    if failure == "storage_denied":
        case.store.read_owner_active_text_bounded.return_value = (
            RepositoryResult(success=False, error="source_unavailable")
        )
    elif failure == "storage_exception":
        case.store.read_owner_active_text_bounded.side_effect = RuntimeError(
            "secret backend details must remain private"
        )
    elif failure in {
        "foreign_tenant", "foreign_owner", "foreign_artifact",
        "unsafe_filename", "invalid_mime", "wrong_digest", "changed_bytes",
    }:
        field, value = {
            "foreign_tenant": ("tenant_id", str(uuid.uuid4())),
            "foreign_owner": ("user_id", str(uuid.uuid4())),
            "foreign_artifact": ("artifact_id", str(uuid.uuid4())),
            "unsafe_filename": ("filename", "../foreign.txt"),
            "invalid_mime": ("mime_type", "application/pdf"),
            "wrong_digest": ("sha256", "broken"),
            "changed_bytes": ("text", _SOURCE_TEXT + " Changed."),
        }[failure]
        case.store.read_owner_active_text_bounded.return_value = (
            RepositoryResult(
                success=True,
                data=replace(case.verified_text, **{field: value}),
            )
        )
    elif failure == "missing_consent":
        case.issuer.verify_current.return_value = None
    elif failure == "evidence_revoked_during_read":
        case.authority.revoke_evidence_after_content = True

    with pytest.raises(PermissionError, match="style_sample_unavailable"):
        await case.analyzer.propose(request=case.request, sample=case.sample)

    case.store.download.assert_not_awaited()
    case.store.read_owner_active_code.assert_not_awaited()
    if failure == "missing_consent":
        case.store.read_owner_active_text_bounded.assert_not_awaited()


async def test_repeated_analysis_does_not_reuse_previously_valid_consent():
    case = _case()
    await case.analyzer.propose(request=case.request, sample=case.sample)
    case.issuer.verify_current.return_value = None

    with pytest.raises(PermissionError, match="style_sample_unavailable"):
        await case.analyzer.propose(request=case.request, sample=case.sample)

    assert case.store.read_owner_active_text_bounded.await_count == 2
    case.store.download.assert_not_awaited()


async def test_consent_revoked_after_read_denies_before_style_analysis():
    case = _case()
    case.issuer.verify_current.side_effect = [
        case.issuer.verify_current.return_value,
        case.issuer.verify_current.return_value,
        None,
    ]

    with pytest.raises(PermissionError, match="style_sample_unavailable"):
        await case.analyzer.propose(request=case.request, sample=case.sample)

    assert case.store.read_owner_active_text_bounded.await_count == 1
    assert case.issuer.verify_current.await_count == 3
    case.store.download.assert_not_awaited()


async def test_document_consent_revoked_during_heuristic_denies_proposal():
    case = _case()
    consent = case.issuer.verify_current.return_value
    # The first complete persisted authority pass performs four consent reads.
    # The final proposal authorization must NOT cache those four positives.
    case.issuer.verify_current.side_effect = [consent] * 4 + [None]

    with pytest.raises(PermissionError, match="style_sample_unavailable"):
        await case.analyzer.propose(
            request=case.request, sample=case.sample,
        )
    assert case.store.read_owner_active_text_bounded.await_count == 1
    assert case.issuer.verify_current.await_count == 5
    assert case.store.download.await_count == 0


async def test_persisted_evidence_revoked_between_heuristic_and_proposal():
    case = _case()
    read_evidence = case.authority._read_evidence
    calls = 0

    async def revoked_after_first_pass(request, sample, source_type, source_id):
        nonlocal calls
        calls += 1
        if calls > 2:
            return None
        return await read_evidence(request, sample, source_type, source_id)

    case.authority._read_evidence = revoked_after_first_pass
    with pytest.raises(PermissionError, match="style_sample_unavailable"):
        await case.analyzer.propose(
            request=case.request, sample=case.sample,
        )
    assert calls == 3
    assert case.store.read_owner_active_text_bounded.await_count == 1
    case.store.download.assert_not_awaited()
