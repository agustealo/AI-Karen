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
    # A fake row cannot establish database authorization: require the actual
    # statement to retain every source/consent lifetime and owner fence.
    statement, params = session.execute.await_args.args
    sql = str(statement)
    for mandatory in (
        "FOR SHARE OF c, f, p",
        "c.revoked_at IS NULL",
        "c.expires_at>clock_timestamp()",
        "c.author_attested IS TRUE",
        "c.analysis_allowed IS TRUE",
        "f.deleted_at IS NULL",
        "f.sha256=c.source_sha256",
        "f.owner_user_id=c.author_actor_id",
        "p.owner_actor_id=c.owner_actor_id",
        "f.bytes BETWEEN 1 AND 65536",
        "p.state<>'revoked'",
    ):
        assert mandatory in sql
    assert params == {
        "tenant": scope["tenant_id"],
        "profile": scope["profile_id"],
        "actor": scope["actor_id"],
        "artifact": scope["artifact_id"],
    }


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



async def test_default_issuer_cannot_mint_or_revoke_a_receipt():
    issuer, scope, session, _ = fixture()
    assert await issuer.issue_first_party(
        **scope, analysis_allowed=True, style_use_allowed=True,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        correlation_id="no-policy",
    ) is None
    assert await issuer.revoke_first_party(**scope, correlation_id="no-policy") is False
    session.execute.assert_not_awaited()


@pytest.mark.parametrize("case", [
    "policy_denied", "falsey_consent", "expired", "invalid_scope",
    "invalid_correlation", "naive_expiry", "wrong_use_type",
])
async def test_issue_denied_without_trusted_complete_authorization(case):
    _, scope, session, _ = fixture()
    policy = SimpleNamespace(
        authorize_issuance=AsyncMock(return_value=True),
        authorize_revocation=AsyncMock(return_value=True),
    )
    client = SimpleNamespace(get_async_session=lambda: FakeContext(session))
    issuer = PostgresDocumentStyleConsentIssuer(
        client_factory=lambda: client, issuance_policy=policy
    )
    request = dict(
        **scope, analysis_allowed=True, style_use_allowed=False,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        correlation_id="consent-correlation",
    )
    if case == "policy_denied":
        policy.authorize_issuance.return_value = False
    elif case == "falsey_consent":
        request["analysis_allowed"] = False
    elif case == "expired":
        request["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif case == "invalid_scope":
        request["artifact_id"] = "arbitrary-document-id"
    elif case == "invalid_correlation":
        request["correlation_id"] = " "
    elif case == "naive_expiry":
        request["expires_at"] = datetime.utcnow()
    elif case == "wrong_use_type":
        request["style_use_allowed"] = 1
    assert await issuer.issue_first_party(**request) is None
    session.execute.assert_not_awaited()


async def test_server_generated_receipt_uses_canonical_file_digest():
    _, scope, session, _ = fixture()
    class DbRow:
        def first(self):
            return ("a" * 64,)
    session.execute.side_effect = [
        FakeResult(None), FakeResult(None), FakeResult(None),
        DbRow(), FakeResult(None),
    ]
    policy = SimpleNamespace(
        authorize_issuance=AsyncMock(return_value=True),
        authorize_revocation=AsyncMock(return_value=True),
    )
    client = SimpleNamespace(get_async_session=lambda: FakeContext(session))
    issuer = PostgresDocumentStyleConsentIssuer(
        client_factory=lambda: client, issuance_policy=policy
    )
    receipt = await issuer.issue_first_party(
        **scope, analysis_allowed=True, style_use_allowed=True,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        correlation_id="author-issued",
    )
    assert str(uuid.UUID(receipt)) == receipt
    assert session.execute.await_count == 5
    params = session.execute.await_args_list[-1].args[1]
    assert params["digest"] == "a" * 64
    assert params["receipt"] == receipt
    assert params["actor"] == scope["actor_id"]
    assert params["artifact"] == scope["artifact_id"]


async def test_revocation_requires_host_permission_and_scope():
    _, scope, session, _ = fixture()
    policy = SimpleNamespace(
        authorize_issuance=AsyncMock(return_value=True),
        authorize_revocation=AsyncMock(return_value=False),
    )
    client = SimpleNamespace(get_async_session=lambda: FakeContext(session))
    issuer = PostgresDocumentStyleConsentIssuer(
        client_factory=lambda: client, issuance_policy=policy
    )
    assert await issuer.revoke_first_party(**scope, correlation_id="deny-revoke") is False
    session.execute.assert_not_awaited()
    policy.authorize_revocation.return_value = True
    class Changed:
        def first(self):
            return (uuid.uuid4(),)
    session.execute.side_effect = [
        FakeResult(None), FakeResult(None), FakeResult(None), Changed(),
    ]
    assert await issuer.revoke_first_party(**scope, correlation_id="revoke") is True
    assert session.execute.await_count == 4
    assert "UPDATE public.writing_style_document_consents" in str(
        session.execute.await_args_list[-1].args[0]
    )
