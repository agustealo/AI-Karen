"""Contract tests: a string source reference is never permission to learn."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.services.writing_style_profile_repository import WritingStyleAccessDenied
from ai_karen_engine.services.writing_style_sample_provenance import (
    VerifiedWritingStyleSource,
    WritingStyleSampleProvenance,
)

pytestmark = pytest.mark.asyncio


def sample_data():
    return {
        "tenant_id": str(uuid.uuid4()), "actor_id": str(uuid.uuid4()),
        "profile_id": str(uuid.uuid4()), "sample_id": str(uuid.uuid4()),
        "source_type": "document", "source_id": str(uuid.uuid4()),
        "correlation_id": "test-source-consent",
    }


def verified(data, **changes):
    fields = {
        "tenant_id": data["tenant_id"],
        "profile_id": data["profile_id"],
        "owner_actor_id": data["actor_id"],
        "source_id": data["source_id"],
        "source_type": data["source_type"],
        "author_actor_id": str(uuid.uuid4()),
        "consent_receipt_id": str(uuid.uuid4()),
        "analysis_allowed": True,
        "style_use_allowed": False,
        "consent_expires_at": datetime.now(timezone.utc) + timedelta(days=1),
    }
    fields.update(changes)
    return VerifiedWritingStyleSource(**fields)


async def test_host_authority_required():
    with pytest.raises(ValueError, match="writing_style_source_authority_required"):
        WritingStyleSampleProvenance(authority=None)


@pytest.mark.parametrize("denial", ["none", "exception", "no_consent", "other_tenant", "expired"])
async def test_denied_untrusted_source_never_reaches_database(denial):
    data = sample_data()
    authority = type("Authority", (), {"verify_analysis": AsyncMock()})()
    if denial == "none":
        authority.verify_analysis.return_value = None
    elif denial == "exception":
        authority.verify_analysis.side_effect = RuntimeError("private credential")
    elif denial == "no_consent":
        authority.verify_analysis.return_value = verified(data, analysis_allowed=False)
    elif denial == "other_tenant":
        authority.verify_analysis.return_value = verified(data, tenant_id=str(uuid.uuid4()))
    else:
        authority.verify_analysis.return_value = verified(
            data, consent_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
        )
    repo = WritingStyleSampleProvenance(
        authority=authority,
        client_factory=lambda: pytest.fail("denied source must not open database"),
    )
    with pytest.raises(WritingStyleAccessDenied, match="style_source_unavailable") as failure:
        await repo.register(**data)
    assert "credential" not in str(failure.value)
    authority.verify_analysis.assert_awaited_once_with(
        tenant_id=data["tenant_id"], actor_id=data["actor_id"],
        profile_id=data["profile_id"], source_type="document", source_id=data["source_id"],
    )


async def test_bad_source_type_denied_before_authority_or_database():
    data = sample_data()
    data["source_type"] = "file:///etc/passwd"
    authority = type("Authority", (), {"verify_analysis": AsyncMock()})()
    repo = WritingStyleSampleProvenance(
        authority=authority,
        client_factory=lambda: pytest.fail("invalid source must not open database"),
    )
    with pytest.raises(ValueError, match="invalid_style_source_type"):
        await repo.register(**data)
    authority.verify_analysis.assert_not_awaited()


async def test_verified_receipt_requires_canonical_fields():
    data = sample_data()
    with pytest.raises(ValueError, match="invalid_style_source_scope"):
        verified(data, source_id="arbitrary-opaque-string")
    with pytest.raises(ValueError, match="invalid_style_source_consent"):
        verified(data, analysis_allowed=1)
    with pytest.raises(ValueError, match="invalid_style_source_expiration"):
        verified(data, consent_expires_at=datetime(2026, 1, 1))
