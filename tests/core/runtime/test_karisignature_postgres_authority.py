"""WS-02: exact owner/purpose, revision and consent guards on PostgreSQL reads."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.prompt.karisignature_contract import (
    KariSignatureRequest,
    KariSignatureResolver,
    KariSignatureRevision,
)
from ai_karen_engine.platform.personalization import karisignature_repository as mod


TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
PROFILE = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
REVISION = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
EXPRESSION = {"tone": "direct", "register": "professional"}


def request(*, tenant=TENANT, owner=OWNER, purpose="draft_email"):
    return KariSignatureRequest(
        tenant_id=tenant, actor_id=owner, profile_id=PROFILE,
        purpose=purpose, correlation_id="ws02-request",
    )


def row(**changes):
    data = {
        "profile_id": uuid.UUID(PROFILE),
        "tenant_id": uuid.UUID(TENANT),
        "owner_user_id": uuid.UUID(OWNER),
        "current_revision_id": uuid.UUID(REVISION),
        "revision_counter": 2,
        "revision_id": uuid.UUID(REVISION),
        "revision_number": 2,
        "state": "published",
        "approved_expression": dict(EXPRESSION),
        "content_digest": KariSignatureRevision.digest(EXPRESSION),
    }
    data.update(changes)
    return data


def scoped_database(monkeypatch, current):
    queries = []
    scopes = []

    class Session:
        async def execute(self, statement, params):
            queries.append((str(statement), dict(params)))
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(
                    one_or_none=lambda: current() if callable(current) else current
                )
            )

    @asynccontextmanager
    async def transaction(*, tenant_id, user_id):
        scopes.append((tenant_id, user_id))
        yield Session()

    monkeypatch.setattr(mod, "async_transaction_scope", transaction)
    return queries, scopes


@pytest.mark.asyncio
async def test_authorized_live_resolution_rechecks_same_actor_and_purpose(monkeypatch):
    queries, scopes = scoped_database(monkeypatch, row())
    authority = mod.PostgresKariSignatureAuthority()
    result = await KariSignatureResolver(authority).resolve(request())
    assert result.presentation == EXPRESSION
    assert result.revision_id == REVISION
    assert result.revision_number == 2
    assert scopes == [(TENANT, OWNER), (TENANT, OWNER)]
    assert len(queries) == 2
    for statement, params in queries:
        assert "FOR SHARE OF p, r" in statement
        assert "p.owner_user_id = CAST(:actor_id AS uuid)" in statement
        assert "p.consent_state = 'granted'" in statement
        assert params == {
            "tenant_id": TENANT, "actor_id": OWNER,
            "profile_id": PROFILE, "purpose": "draft_email",
        }


@pytest.mark.asyncio
async def test_missing_or_revoked_row_cannot_resolve(monkeypatch):
    state = {"current": row()}
    queries, _ = scoped_database(monkeypatch, lambda: state["current"])
    resolver = KariSignatureResolver(mod.PostgresKariSignatureAuthority())
    assert (await resolver.resolve(request())).revision_id == REVISION
    state["current"] = None
    with pytest.raises(PermissionError, match="style_unavailable"):
        await resolver.resolve(request())
    assert len(queries) == 3


@pytest.mark.asyncio
async def test_permission_revoked_between_read_and_final_gate_is_denied(monkeypatch):
    values = [row(), None]
    scoped_database(monkeypatch, lambda: values.pop(0))
    with pytest.raises(PermissionError, match="style_unavailable"):
        await KariSignatureResolver(mod.PostgresKariSignatureAuthority()).resolve(request())


@pytest.mark.asyncio
@pytest.mark.parametrize("field,new_value", [
    ("revision_id", uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")),
    ("current_revision_id", uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")),
    ("revision_number", 1),
    ("revision_counter", 1),
    ("tenant_id", uuid.UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")),
    ("owner_user_id", uuid.UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")),
    ("approved_expression", {"provider": "external"}),
    ("content_digest", "0" * 64),
])
async def test_revision_drift_or_untrusted_fields_are_denied(monkeypatch, field, new_value):
    scoped_database(monkeypatch, row(**{field: new_value}))
    with pytest.raises(PermissionError, match="style_unavailable"):
        await KariSignatureResolver(mod.PostgresKariSignatureAuthority()).resolve(request())


@pytest.mark.asyncio
async def test_sql_backend_failure_is_denied_without_disclosing_exception(monkeypatch):
    @asynccontextmanager
    async def failed_transaction(*, tenant_id, user_id):
        raise RuntimeError("sensitive backend connection details")
        yield

    monkeypatch.setattr(mod, "async_transaction_scope", failed_transaction)
    with pytest.raises(PermissionError, match="style_unavailable") as err:
        await KariSignatureResolver(mod.PostgresKariSignatureAuthority()).resolve(request())
    assert "sensitive" not in str(err.value)


@pytest.mark.asyncio
async def test_owner_and_purpose_are_forwarded_to_rls_not_taken_from_revision(monkeypatch):
    queries, scopes = scoped_database(monkeypatch, None)
    authority = mod.PostgresKariSignatureAuthority()
    foreign = request(owner="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee", purpose="client_draft")
    assert await authority.read_current_published(request=foreign) is None
    assert scopes == [(TENANT, foreign.actor_id)]
    assert queries[0][1]["purpose"] == "client_draft"
    assert queries[0][1]["actor_id"] == foreign.actor_id
