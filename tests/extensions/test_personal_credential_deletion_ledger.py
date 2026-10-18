"""KOC-07 request ownership, idempotency, and truthful persistence semantics."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from ai_karen_engine.persistence.repositories import channel_repository as module

TENANT = str(uuid.uuid4())
USER = str(uuid.uuid4())
OTHER = str(uuid.uuid4())
REQUEST = str(uuid.uuid4())
ARGS = {
    "tenant_id": TENANT,
    "connection_id": "connection-1",
    "user_id": USER,
    "provider_id": "operator-1",
    "connection_revision": 2,
    "session_reference": "operator-session",
    "credential_scope": "companion-credentials",
    "idempotency_key": "disconnect-intent-1",
}


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def mappings(self):
        return self

    def one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, *, revision=2, existing=None, inserted=None):
        self.revision = revision
        self.existing = existing
        self.inserted = {"request_id": uuid.UUID(REQUEST), "status": "requested"} if inserted is None else inserted
        self.queries = []

    async def execute(self, statement, params):
        sql = str(statement)
        self.queries.append((sql, params))
        if "SELECT c.revision" in sql:
            return FakeResult(self.revision)
        if "SELECT request_id, user_id" in sql:
            return FakeResult(self.existing)
        if "INSERT INTO public.channel_personal_credential_deletions" in sql:
            return FakeResult(self.inserted)
        raise AssertionError("Unexpected repository SQL")


def install(monkeypatch, session):
    @asynccontextmanager
    async def fake_transaction(tenant_id):
        assert tenant_id == TENANT
        yield session

    monkeypatch.setattr(module, "async_transaction_scope", fake_transaction)


@pytest.mark.asyncio
async def test_new_request_records_intent_not_erasure(monkeypatch):
    session = FakeSession()
    install(monkeypatch, session)
    result = await module.SqlChannelRepository().request_personal_credential_deletion(**ARGS)
    assert result == {"request_id": REQUEST, "status": "requested"}
    assert len(session.queries) == 3
    assert "FOR UPDATE OF c" in session.queries[0][0]
    assert "ON CONFLICT" in session.queries[2][0]
    assert "verified" not in result["status"]


@pytest.mark.asyncio
async def test_same_idempotency_returns_existing_request(monkeypatch):
    session = FakeSession(existing={
        "request_id": uuid.UUID(REQUEST),
        "user_id": uuid.UUID(USER),
        "session_reference": ARGS["session_reference"],
        "credential_scope": ARGS["credential_scope"],
        "status": "provider_pending",
    })
    install(monkeypatch, session)
    result = await module.SqlChannelRepository().request_personal_credential_deletion(**ARGS)
    assert result == {"request_id": REQUEST, "status": "provider_pending"}
    assert len(session.queries) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [
    {"user_id": uuid.UUID(OTHER)},
    {"session_reference": "unrelated-session"},
    {"credential_scope": "other-secrets"},
])
async def test_same_key_different_scope_is_denied(monkeypatch, changed):
    existing = {
        "request_id": uuid.UUID(REQUEST), "user_id": uuid.UUID(USER),
        "session_reference": ARGS["session_reference"],
        "credential_scope": ARGS["credential_scope"],
        "status": "requested", **changed,
    }
    session = FakeSession(existing=existing)
    install(monkeypatch, session)
    with pytest.raises(ValueError, match="Idempotency key reused"):
        await module.SqlChannelRepository().request_personal_credential_deletion(**ARGS)


@pytest.mark.asyncio
@pytest.mark.parametrize("revision", [None, 1, 3])
async def test_missing_owner_or_changed_revision_fails(monkeypatch, revision):
    session = FakeSession(revision=revision)
    install(monkeypatch, session)
    with pytest.raises(ValueError, match="owner or revision"):
        await module.SqlChannelRepository().request_personal_credential_deletion(**ARGS)
    assert len(session.queries) == 1


@pytest.mark.asyncio
async def test_concurrent_insert_conflict_does_not_claim_success(monkeypatch):
    session = FakeSession()
    session.inserted = None
    install(monkeypatch, session)
    with pytest.raises(ValueError, match="must be retried"):
        await module.SqlChannelRepository().request_personal_credential_deletion(**ARGS)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"idempotency_key": " "},
    {"session_reference": ""},
    {"credential_scope": " "},
    {"provider_id": "x" * 129},
    {"connection_revision": True},
])
async def test_invalid_input_fails_before_sql(monkeypatch, change):
    session = FakeSession()
    install(monkeypatch, session)
    with pytest.raises(ValueError):
        await module.SqlChannelRepository().request_personal_credential_deletion(**{**ARGS, **change})
    assert session.queries == []
