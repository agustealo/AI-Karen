"""KOC-08: durable provider claims are not independent deletion proof."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest

from ai_karen_engine.extensions.channels.contracts import PersonalCredentialErasureReceipt
from ai_karen_engine.persistence.repositories import channel_repository as module

TENANT = str(uuid.uuid4())
USER = str(uuid.uuid4())
REQUEST = str(uuid.uuid4())
NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)
FIELDS = {
    "provider_id": "managed-operator",
    "connection_id": "connection-1",
    "connection_revision": 3,
    "session_reference": "vendor-session",
    "deletion_request_id": REQUEST,
    "provider_receipt_id": "vendor-ack",
    "credential_scope": "companion-credentials",
    "erased_at": NOW,
}


class Result:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def one_or_none(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value


class Session:
    def __init__(self, *, changes=None):
        self.record = {
            "provider_id": FIELDS["provider_id"],
            "user_id": uuid.UUID(USER),
            "connection_revision": 3,
            "live_revision": 3,
            "session_reference": FIELDS["session_reference"],
            "credential_scope": FIELDS["credential_scope"],
            "status": "requested",
            "provider_receipt_id": None,
            **(changes or {}),
        }
        self.statements = []

    async def execute(self, statement, params):
        sql = str(statement)
        self.statements.append(sql)
        if "SELECT d.provider_id" in sql:
            return Result(self.record)
        if "UPDATE public.channel_personal_credential_deletions" in sql:
            return Result(uuid.UUID(REQUEST))
        raise AssertionError("Unexpected SQL")


def inject(monkeypatch, session):
    @asynccontextmanager
    async def scope(tenant):
        assert tenant == TENANT
        yield session

    monkeypatch.setattr(module, "async_transaction_scope", scope)


async def call(receipt):
    return await module.SqlChannelRepository().record_personal_credential_deletion_claim(
        tenant_id=TENANT, request_id=REQUEST, connection_id="connection-1",
        user_id=USER, receipt=receipt,
    )


@pytest.mark.asyncio
async def test_host_evidenced_claim_only_writes_provider_claimed(monkeypatch):
    session = Session()
    inject(monkeypatch, session)
    assert await call(PersonalCredentialErasureReceipt(**FIELDS)) is True
    assert len(session.statements) == 2
    assert "status = 'provider_claimed'" in session.statements[1]
    assert "status = 'verified'" not in session.statements[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"provider_id": "foreign"},
    {"session_reference": "foreign"},
    {"credential_scope": "unrelated"},
    {"connection_revision": 4},
    {"deletion_request_id": str(uuid.uuid4())},
])
async def test_wrong_provider_claim_rejected(monkeypatch, change):
    session = Session()
    inject(monkeypatch, session)
    with pytest.raises(ValueError, match="durable request"):
        await call(PersonalCredentialErasureReceipt(**{**FIELDS, **change}))
    assert len(session.statements) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"live_revision": 4},
    {"status": "verified"},
    {"status": "unknown"},
])
async def test_stale_or_invalid_transition_rejected(monkeypatch, changes):
    session = Session(changes=changes)
    inject(monkeypatch, session)
    with pytest.raises(ValueError):
        await call(PersonalCredentialErasureReceipt(**FIELDS))
    assert len(session.statements) == 1


@pytest.mark.asyncio
async def test_matching_duplicate_receipt_is_idempotent(monkeypatch):
    session = Session(changes={"status": "provider_claimed", "provider_receipt_id": "vendor-ack"})
    inject(monkeypatch, session)
    assert await call(PersonalCredentialErasureReceipt(**FIELDS)) is True
    assert len(session.statements) == 1


@pytest.mark.asyncio
async def test_conflicting_duplicate_receipt_fails_closed(monkeypatch):
    session = Session(changes={"status": "provider_claimed", "provider_receipt_id": "different"})
    inject(monkeypatch, session)
    assert await call(PersonalCredentialErasureReceipt(**FIELDS)) is False
    assert len(session.statements) == 1
