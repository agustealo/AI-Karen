"""Repository proof for durable, tenant-bound, at-most-once provider dispatch."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from ai_karen_engine.extensions.channels.contracts import (
    ChannelDeliveryReceipt,
    ChannelDeliveryState,
)
from ai_karen_engine.persistence.repositories import channel_repository as module
from ai_karen_engine.persistence.repositories.channel_repository import SqlChannelRepository

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DELIVERY = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
CLAIM = "cccccccc-cccc-cccc-cccc-cccccccccccc"


class RowResult:
    def __init__(self, row=None, scalar=None, rows=None):
        self.row = row
        self.scalar = scalar
        self.rows = [] if rows is None else rows

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row

    def scalar_one_or_none(self):
        return self.scalar

    def scalars(self):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), dict(params)))
        return self.results.pop(0)


def install(monkeypatch, session):
    @asynccontextmanager
    async def scope(tenant_id):
        assert tenant_id == TENANT
        yield session
    monkeypatch.setattr(module, "async_transaction_scope", scope)


@pytest.mark.asyncio
async def test_outbound_claim_binds_current_revision_identity_and_user(monkeypatch):
    session = FakeSession(RowResult(row={
        "delivery_id": DELIVERY, "tenant_id": TENANT, "connection_id": "conn",
        "destination_id": "native-room", "idempotency_key": "inbox-1",
        "message_kind": "text", "message_text": "answer",
        "installation_id": "channel-plugin",
        "provider_account_id": "native-account",
        "credential_handle": "vault://credential", "revision": 3,
        "enabled": True,
        "user_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "external_conversation_id": "native-room",
    }))
    install(monkeypatch, session)
    claim = await SqlChannelRepository().claim_outbound(
        tenant_id=TENANT, delivery_id=DELIVERY, lease_seconds=90,
    )
    assert claim is not None
    assert claim.delivery.delivery_id == DELIVERY
    assert claim.connection.revision == 3
    assert claim.user_id == "dddddddd-dddd-dddd-dddd-dddddddddddd"
    assert claim.external_conversation_id == "native-room"
    sql, args = session.calls[0]
    for guard in (
        "o.status = 'accepted'",
        "o.claim_token IS NULL",
        "o.claim_expires_at IS NULL",
        "c.revision = i.connection_revision",
        "b.revoked_at IS NULL",
        "u.is_active = true",
        "i.status = 'completed'",
        "o.tenant_id = CAST(:tenant AS uuid)",
    ):
        assert guard in sql
    assert args["tenant"] == TENANT
    assert args["delivery"] == DELIVERY
    assert "credential_handle" not in args
    assert "user_id" not in args


@pytest.mark.asyncio
async def test_claim_when_not_eligible_returns_no_delivery(monkeypatch):
    session = FakeSession(RowResult(row=None))
    install(monkeypatch, session)
    assert await SqlChannelRepository().claim_outbound(
        tenant_id=TENANT, delivery_id=DELIVERY, lease_seconds=90,
    ) is None


@pytest.mark.asyncio
async def test_receipt_persists_only_with_unexpired_matching_token(monkeypatch):
    session = FakeSession(RowResult(scalar=DELIVERY))
    install(monkeypatch, session)
    success = await SqlChannelRepository().finalize_outbound_claim(
        tenant_id=TENANT, claim_token=CLAIM,
        receipt=ChannelDeliveryReceipt(
            delivery_id=DELIVERY, state=ChannelDeliveryState.SENT,
            provider_message_id="real-provider-id",
        ),
    )
    assert success
    sql, args = session.calls[0]
    assert "claim_token = CAST(:claim AS uuid)" in sql
    assert "claim_expires_at > clock_timestamp()" in sql
    assert "provider_message_id = :provider_message" in sql
    assert args["state"] == "sent"
    assert args["provider_message"] == "real-provider-id"


@pytest.mark.asyncio
async def test_internal_accepted_is_not_a_provider_receipt():
    with pytest.raises(ValueError, match="not a provider send receipt"):
        await SqlChannelRepository().finalize_outbound_claim(
            tenant_id=TENANT, claim_token=CLAIM,
            receipt=ChannelDeliveryReceipt(
                delivery_id=DELIVERY, state=ChannelDeliveryState.ACCEPTED,
            ),
        )


@pytest.mark.asyncio
async def test_ambiguous_expired_claim_is_quarantined_never_requeued(monkeypatch):
    session = FakeSession(RowResult(rows=[DELIVERY]))
    install(monkeypatch, session)
    results = await SqlChannelRepository().quarantine_expired_outbound_claims(
        tenant_id=TENANT,
    )
    assert results == [DELIVERY]
    sql, args = session.calls[0]
    assert "SET status = 'unknown'" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "claim_expires_at <= clock_timestamp()" in sql
    assert "'delivery_receipt_unknown'" in sql
    assert args["tenant"] == TENANT
    assert "SET status = 'accepted'" not in sql


@pytest.mark.asyncio
async def test_explicit_missing_delivery_never_contacts_provider_or_claims(monkeypatch):
    session = FakeSession(RowResult(row=None))
    install(monkeypatch, session)
    assert await SqlChannelRepository().get_delivery_preflight(
        tenant_id=TENANT, delivery_id=DELIVERY,
    ) is None
    assert "o.tenant_id = CAST(:tenant AS uuid)" in session.calls[0][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [0, 3601, -5])
async def test_outbound_lease_enforces_bounds_before_sql(bad):
    with pytest.raises(ValueError, match="lease"):
        await SqlChannelRepository().claim_outbound(
            tenant_id=TENANT, delivery_id=DELIVERY, lease_seconds=bad,
        )

@pytest.mark.asyncio
async def test_repository_rejects_unproven_success_without_sql():
    store = SqlChannelRepository()
    for state, mid, rid in [
        (ChannelDeliveryState.SENT, None, None),
        (ChannelDeliveryState.DELIVERED, "msg", None),
        (ChannelDeliveryState.READ, None, "receipt"),
    ]:
        with pytest.raises(ValueError, match="evidence"):
            await store.finalize_outbound_claim(
                tenant_id=TENANT, claim_token=CLAIM,
                receipt=ChannelDeliveryReceipt(
                    delivery_id=DELIVERY, state=state,
                    provider_message_id=mid, provider_receipt_id=rid,
                ),
            )
