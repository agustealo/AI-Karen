"""WS-02C: current source owner, content and evidence must all agree."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.runtime.prompt.karisignature_contract import (
    KariSignatureRequest,
)
from ai_karen_engine.services.formatting.karisignature_sample_analysis import (
    KariSignatureSample,
)
from ai_karen_engine.services.formatting.karisignature_persisted_sample_authority import (
    WritingStylePersistedSampleAuthority,
    _Evidence,
)
from ai_karen_engine.services.writing_style_sample_provenance import (
    VerifiedWritingStyleSource,
)

pytestmark = pytest.mark.asyncio


def authorized_case():
    tenant, actor, profile, sample_id, source_id = (
        str(uuid.uuid4()) for _ in range(5)
    )
    body = " ".join(["Original words from an authorized source document"] * 5)
    sample = KariSignatureSample(
        tenant_id=tenant, actor_id=actor, profile_id=profile,
        sample_id=sample_id, source_ref=f"document:{source_id}",
        content=body, digest=KariSignatureSample.content_digest(body),
    )
    request = KariSignatureRequest(
        tenant_id=tenant, actor_id=actor, profile_id=profile,
        purpose="analyze_style", correlation_id="source-authority-test",
    )
    author = str(uuid.uuid4())
    consent = str(uuid.uuid4())
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    evidence = _Evidence(author, consent, expiry)
    verified = VerifiedWritingStyleSource(
        tenant_id=tenant, profile_id=profile, owner_actor_id=actor,
        source_id=source_id, source_type="document", author_actor_id=author,
        consent_receipt_id=consent, analysis_allowed=True,
        style_use_allowed=False, consent_expires_at=expiry,
    )
    source = type("Source", (), {"verify_analysis": AsyncMock(return_value=verified)})()
    reader = type(
        "Content", (), {"read_current_content": AsyncMock(return_value=body)}
    )()

    class EvidenceAdapter(WritingStylePersistedSampleAuthority):
        async def _read_evidence(self, request, sample, source_type, source_id):
            return evidence

    return EvidenceAdapter(
        source_authority=source, content_reader=reader
    ), request, sample, source, reader, verified, evidence


async def test_matching_evidence_and_current_source_bytes_authorizes():
    adapter, request, sample, source, reader, _, _ = authorized_case()
    assert await adapter.authorize_analysis(request=request, sample=sample)
    assert source.verify_analysis.await_count == 2
    reader.read_current_content.assert_awaited_once_with(
        tenant_id=request.tenant_id, actor_id=request.actor_id,
        source_type="document", source_id=sample.source_ref.split(":")[1],
    )


async def test_request_purpose_must_be_analysis():
    adapter, request, sample, source, reader, _, _ = authorized_case()
    wrong = KariSignatureRequest(
        tenant_id=request.tenant_id, actor_id=request.actor_id,
        profile_id=request.profile_id, purpose="draft_email",
        correlation_id=request.correlation_id,
    )
    assert not await adapter.authorize_analysis(request=wrong, sample=sample)
    source.verify_analysis.assert_not_awaited()
    reader.read_current_content.assert_not_awaited()


@pytest.mark.parametrize(
    "failure",
    ["changed_content", "missing_content", "wrong_author", "wrong_receipt",
     "expired", "owner_denied", "owner_error", "revoked_between_checks"],
)
async def test_fail_closed_on_source_drift_or_revocation(failure):
    adapter, request, sample, source, reader, verified, evidence = authorized_case()
    if failure == "changed_content":
        reader.read_current_content.return_value = sample.content + " changed"
    elif failure == "missing_content":
        reader.read_current_content.return_value = None
    elif failure == "wrong_author":
        source.verify_analysis.return_value = VerifiedWritingStyleSource(
            **{**verified.__dict__, "author_actor_id": str(uuid.uuid4())}
        )
    elif failure == "wrong_receipt":
        source.verify_analysis.return_value = VerifiedWritingStyleSource(
            **{**verified.__dict__, "consent_receipt_id": str(uuid.uuid4())}
        )
    elif failure == "expired":
        source.verify_analysis.return_value = VerifiedWritingStyleSource(
            **{**verified.__dict__, "consent_expires_at":
               datetime.now(timezone.utc) - timedelta(seconds=1)}
        )
    elif failure == "owner_denied":
        source.verify_analysis.return_value = None
    elif failure == "owner_error":
        source.verify_analysis.side_effect = RuntimeError("secret source token")
    else:
        source.verify_analysis.side_effect = [verified, None]
    assert not await adapter.authorize_analysis(request=request, sample=sample)


async def test_sample_ref_must_match_canonical_source_identity():
    adapter, request, sample, source, reader, _, _ = authorized_case()
    bad = KariSignatureSample(
        tenant_id=sample.tenant_id, actor_id=sample.actor_id,
        profile_id=sample.profile_id, sample_id=sample.sample_id,
        source_ref="document:arbitrary-document",
        content=sample.content, digest=sample.digest,
    )
    assert not await adapter.authorize_analysis(request=request, sample=bad)
    source.verify_analysis.assert_not_awaited()
    reader.read_current_content.assert_not_awaited()


async def test_missing_live_source_dependency_rejected():
    _, _, _, source, reader, _, _ = authorized_case()
    with pytest.raises(ValueError, match="writing_style_live_source_owner_required"):
        WritingStylePersistedSampleAuthority(
            source_authority=source, content_reader=None
        )
