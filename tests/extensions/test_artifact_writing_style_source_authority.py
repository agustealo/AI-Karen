"""WS-04A2 regression: document ownership is necessary, never style consent."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.services.artifact_writing_style_source_authority import (
    ArtifactWritingStyleSourceAuthority,
)
from ai_karen_engine.services.writing_style_sample_provenance import (
    VerifiedWritingStyleSource,
)

pytestmark = pytest.mark.asyncio


def scope():
    return dict(
        tenant_id=str(uuid.uuid4()),
        actor_id=str(uuid.uuid4()),
        profile_id=str(uuid.uuid4()),
        source_type="document",
        source_id=str(uuid.uuid4()),
    )


def decision(s, *, author=None, analysis=True, style_use=False, expiry=None):
    return VerifiedWritingStyleSource(
        tenant_id=s["tenant_id"],
        owner_actor_id=s["actor_id"],
        profile_id=s["profile_id"],
        source_type="document",
        source_id=s["source_id"],
        author_actor_id=author or s["actor_id"],
        consent_receipt_id=str(uuid.uuid4()),
        analysis_allowed=analysis,
        style_use_allowed=style_use,
        consent_expires_at=expiry,
    )


def artifact_result(s, *, owner=None, tenant=None, kind="document", deleted=None):
    return SimpleNamespace(
        success=True,
        data=SimpleNamespace(
            id=s["source_id"],
            tenant_id=tenant or s["tenant_id"],
            user_id=owner or s["actor_id"],
            kind=kind,
            sha256="a" * 64,
            deleted_at=deleted,
            metadata={"consent_receipt_id": str(uuid.uuid4()), "style_use_allowed": True},
        ),
    )


def adapter(s, *, result=None, consent=None):
    artifacts = SimpleNamespace(
        get_metadata=AsyncMock(return_value=artifact_result(s) if result is None else result)
    )
    issuer = SimpleNamespace(
        verify_current=AsyncMock(return_value=consent)
    )
    return ArtifactWritingStyleSourceAuthority(
        artifacts=artifacts, consent_issuer=issuer
    ), artifacts, issuer


async def test_required_separate_trusted_issuer():
    with pytest.raises(ValueError, match="artifact_source_owner_required"):
        ArtifactWritingStyleSourceAuthority(artifacts=None, consent_issuer=object())
    with pytest.raises(ValueError, match="document_style_consent_issuer_required"):
        ArtifactWritingStyleSourceAuthority(
            artifacts=SimpleNamespace(get_metadata=AsyncMock()), consent_issuer=None
        )


async def test_metadata_cannot_grant_consent_without_issuer():
    s = scope()
    authority, artifacts, issuer = adapter(s)
    assert await authority.verify_analysis(**s) is None
    artifacts.get_metadata.assert_awaited_once_with(s["source_id"], s["tenant_id"])
    issuer.verify_current.assert_awaited_once()


async def test_live_owner_and_explicit_independent_consent():
    s = scope()
    permitted = decision(s, style_use=False)
    authority, _, issuer = adapter(s, consent=permitted)
    result = await authority.verify_analysis(**s)
    assert result == permitted
    assert result.style_use_allowed is False
    issuer.verify_current.return_value = decision(s, style_use=True)
    result = await authority.verify_analysis(**s)
    assert result is not None and result.style_use_allowed is True
    issuer.verify_current.return_value = None
    assert await authority.verify_analysis(**s) is None


@pytest.mark.parametrize("reason", [
    "wrong_owner", "wrong_tenant", "deleted", "research", "absent",
    "other_author", "analysis_denied", "consent_expired", "issuer_error",
    "artifact_error", "wrong_receipt_scope",
])
async def test_fail_closed_no_source_permission_bypass(reason):
    s = scope()
    receipt = decision(s, style_use=True)
    record = artifact_result(s)
    if reason == "wrong_owner":
        record = artifact_result(s, owner=str(uuid.uuid4()))
    elif reason == "wrong_tenant":
        record = artifact_result(s, tenant=str(uuid.uuid4()))
    elif reason == "deleted":
        record = artifact_result(s, deleted=datetime.now(timezone.utc))
    elif reason == "research":
        record = artifact_result(s, kind="search_article")
    elif reason == "absent":
        record = SimpleNamespace(success=True, data=None)
    elif reason == "other_author":
        receipt = decision(s, author=str(uuid.uuid4()))
    elif reason == "analysis_denied":
        receipt = decision(s, analysis=False)
    elif reason == "consent_expired":
        receipt = decision(s, expiry=datetime.now(timezone.utc)-timedelta(seconds=1))
    elif reason == "wrong_receipt_scope":
        receipt = VerifiedWritingStyleSource(
            tenant_id=s["tenant_id"],
            owner_actor_id=s["actor_id"],
            profile_id=str(uuid.uuid4()),
            source_type="document",
            source_id=s["source_id"],
            author_actor_id=s["actor_id"],
            consent_receipt_id=str(uuid.uuid4()),
            analysis_allowed=True,
            style_use_allowed=True,
            consent_expires_at=None,
        )
    authority, artifacts, issuer = adapter(s, result=record, consent=receipt)
    if reason == "issuer_error":
        issuer.verify_current.side_effect = RuntimeError("private credential")
    elif reason == "artifact_error":
        artifacts.get_metadata.side_effect = RuntimeError("private artifact")
    assert await authority.verify_analysis(**s) is None


async def test_unknown_source_type_and_malformed_scope_never_query_database():
    s = scope()
    authority, artifacts, issuer = adapter(s, consent=decision(s))
    for overrides in ({"source_type": "email"}, {"source_id": "../x"},
                      {"tenant_id": "default"}, {"profile_id": "not-a-uuid"}):
        assert await authority.verify_analysis(**(s | overrides)) is None
    artifacts.get_metadata.assert_not_awaited()
    issuer.verify_current.assert_not_awaited()


async def test_live_use_requires_style_use_and_revocation_is_immediate():
    s = scope()
    granted = decision(s, style_use=True)
    authority, artifacts, issuer = adapter(s, consent=granted)
    assert await authority.verify_use(**s) is True
    issuer.verify_current.return_value = decision(s, style_use=False)
    assert await authority.verify_use(**s) is False
    issuer.verify_current.return_value = None
    assert await authority.verify_use(**s) is False
    # A revoked source wins even when the issuer still returns a grant.
    issuer.verify_current.return_value = granted
    artifacts.get_metadata.return_value = artifact_result(
        s, deleted=datetime.now(timezone.utc)
    )
    assert await authority.verify_use(**s) is False


async def test_source_archive_racing_issuer_never_returns_allow():
    s = scope()
    authority, artifacts, issuer = adapter(s, consent=decision(s, style_use=True))
    artifacts.get_metadata.side_effect = [
        artifact_result(s),
        artifact_result(s, deleted=datetime.now(timezone.utc)),
    ]
    assert await authority.verify_analysis(**s) is None
    assert artifacts.get_metadata.await_count == 2
    issuer.verify_current.assert_awaited_once()


async def test_source_revision_drift_during_consent_check_denied():
    s = scope()
    authority, artifacts, _ = adapter(s, consent=decision(s, style_use=True))
    changed = artifact_result(s)
    changed.data.sha256 = "b" * 64
    artifacts.get_metadata.side_effect = [artifact_result(s), changed]
    assert await authority.verify_analysis(**s) is None
