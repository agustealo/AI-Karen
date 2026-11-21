"""WS-04A9C: read-only consent verifier contract tests.

No test fixture grants authority to the runtime or issues a consent receipt.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.services.postgres_document_style_consent_issuer import (
    PostgresDocumentStyleConsentIssuer,
)

pytestmark = pytest.mark.asyncio


class FakeResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row


class FakeContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def fixture():
    tenant, actor, profile, artifact, receipt = (
        str(uuid.uuid4()) for _ in range(5)
    )
    row = {
        "receipt_id": uuid.UUID(receipt),
        "author_actor_id": uuid.UUID(actor),
        "analysis_allowed": True,
        "style_use_allowed": False,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "source_sha256": "a" * 64,
        "sha256": "a" * 64,
    }
    session = SimpleNamespace(execute=AsyncMock(return_value=FakeResult(row)))
    client = SimpleNamespace(get_async_session=lambda: FakeContext(session))
    issuer = PostgresDocumentStyleConsentIssuer(client_factory=lambda: client)
    scope = dict(
        tenant_id=tenant, actor_id=actor,
        profile_id=profile, artifact_id=artifact,
    )
    return issuer, scope, session, row


async def test_valid_receipt_matches_scope_and_preserves_separate_use_permission():
    issuer, scope, session, row = fixture()
    decision = await issuer.verify_current(**scope)
    assert decision is not None
    assert decision.tenant_id == scope["tenant_id"]
    assert decision.source_id == scope["artifact_id"]
    assert decision.consent_receipt_id == str(row["receipt_id"])
    assert decision.analysis_allowed is True
    assert decision.style_use_allowed is False
    assert session.execute.await_count == 4  # three RLS config calls + SELECT


@pytest.mark.parametrize("field", ["tenant_id", "actor_id", "profile_id", "artifact_id"])
async def test_noncanonical_scope_denied_before_database_access(field):
    issuer, scope, session, _ = fixture()
    scope[field] = str(uuid.uuid4()).upper()
    assert await issuer.verify_current(**scope) is None
    session.execute.assert_not_awaited()


@pytest.mark.parametrize("mutation", [
    "missing", "expired", "malformed_digest", "digest_drift",
    "foreign_author", "invalid_receipt", "analysis_denied",
    "invalid_use_value", "naive_expiry",
])
async def test_untrusted_or_stale_receipt_denied(mutation):
    issuer, scope, session, row = fixture()
    if mutation == "missing":
        session.execute.return_value = FakeResult(None)
    elif mutation == "expired":
        row["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif mutation == "malformed_digest":
        row["source_sha256"] = ""
    elif mutation == "digest_drift":
        row["sha256"] = "b" * 64
    elif mutation == "foreign_author":
        row["author_actor_id"] = uuid.uuid4()
    elif mutation == "invalid_receipt":
        row["receipt_id"] = "not-a-uuid"
    elif mutation == "analysis_denied":
        row["analysis_allowed"] = False
    elif mutation == "invalid_use_value":
        row["style_use_allowed"] = 1
    elif mutation == "naive_expiry":
        row["expires_at"] = datetime.utcnow()
    assert await issuer.verify_current(**scope) is None


async def test_database_error_never_becomes_consent():
    issuer, scope, session, _ = fixture()
    session.execute.side_effect = RuntimeError("internal database credential")
    assert await issuer.verify_current(**scope) is None


async def test_no_public_mutation_or_runtime_installation():
    issuer, _, _, _ = fixture()
    assert not hasattr(issuer, "issue")
    assert not hasattr(issuer, "grant")
    assert not hasattr(issuer, "revoke")
