"""Repository proof for durable, tenant-bound, at-most-once provider dispatch."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from ai_karen_engine.extensions.channels.contracts import (
    ChannelDeliveryReceipt,
    ChannelDeliveryState,
    ChannelProviderStatusEvent,
    ChannelConnection,
    ChannelDeliveryRequest,
)
from ai_karen_engine.persistence.repositories import channel_repository as module
from ai_karen_engine.persistence.repositories.channel_repository import (
    ClaimedChannelDelivery, SqlChannelRepository,
)

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


def whatsapp_claim(*, recipient="15551234567", tenant_id=TENANT):
    account = ChannelConnection(
        connection_id="conn-wa", installation_id="whatsapp-cloud",
        tenant_id=tenant_id, provider_account_id="10987654321",
        credential_handle="vault://meta", revision=4, enabled=True,
    )
    return ClaimedChannelDelivery(
        connection=account,
        delivery=ChannelDeliveryRequest(
            delivery_id=DELIVERY, connection_id=account.connection_id,
            destination_id=recipient, idempotency_key="wamid.customer",
            message_kind="text", text="Reply",
        ),
        user_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        external_conversation_id=recipient,
        claim_token=CLAIM,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [True, False])
async def test_whatsapp_window_sql_is_claim_and_identity_scoped(monkeypatch, allowed):
    session = FakeSession(RowResult(scalar=allowed))
    install(monkeypatch, session)
    claim = whatsapp_claim()
    assert await SqlChannelRepository().whatsapp_customer_window_open(
        tenant_id=TENANT, claimed=claim,
    ) is allowed
    sql, args = session.calls[0]
    for protection in (
        "o.claim_token = CAST(:claim AS uuid)",
        "o.claim_expires_at > clock_timestamp()",
        "o.attempt_count = 1",
        "o.destination_id = :recipient",
        "origin.user_id = CAST(:user AS uuid)",
        "c.revision = :revision",
        "c.installation_id = 'whatsapp-cloud'",
        "b.revoked_at IS NULL",
        "customer.binding_id = origin.binding_id",
        "customer.provider_event_at <= clock_timestamp()",
        "customer.provider_event_at >",
        "interval '24 hours'",
        "clock_timestamp()",
    ):
        assert protection in sql
    assert args["claim"] == CLAIM
    assert args["recipient"] == claim.delivery.destination_id
    assert args["tenant"] == TENANT
    assert args["revision"] == 4
    assert args["budget"] == 65


@pytest.mark.asyncio
async def test_whatsapp_window_rejects_cross_tenant_before_database(monkeypatch):
    session = FakeSession()
    install(monkeypatch, session)
    foreign = whatsapp_claim(tenant_id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
    assert not await SqlChannelRepository().whatsapp_customer_window_open(
        tenant_id=TENANT, claimed=foreign,
    )
    assert session.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [0, 121, -2])
async def test_whatsapp_window_rejects_unsafe_network_budget(budget):
    with pytest.raises(ValueError, match="budget"):
        await SqlChannelRepository().whatsapp_customer_window_open(
            tenant_id=TENANT, claimed=whatsapp_claim(),
            send_budget_seconds=budget,
        )


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
    session = FakeSession(
        RowResult(scalar=DELIVERY),
        RowResult(row={
            "connection_id": "conn", "destination_id": "15551234567",
            "connection_revision": 3,
        }),
        RowResult(scalar=None),
    )
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
    assert len(session.calls) == 3
    assert "i.connection_revision" in session.calls[1][0]
    assert "channel_provider_status_events" in session.calls[2][0]
    assert session.calls[2][1]["revision"] == 3


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


@pytest.mark.asyncio
async def test_preflight_refuses_already_attempted_accepted_delivery(monkeypatch):
    session = FakeSession(RowResult(row=None))
    install(monkeypatch, session)
    assert await SqlChannelRepository().get_delivery_preflight(
        tenant_id=TENANT, delivery_id=DELIVERY,
    ) is None
    sql, args = session.calls[0]
    assert "o.attempt_count = 0" in sql
    assert "o.claim_token IS NULL" in sql
    assert "o.claim_expires_at IS NULL" in sql
    assert "o.status = 'accepted'" in sql
    assert args["tenant"] == TENANT


@pytest.mark.asyncio
async def test_outbound_claim_rejects_every_prior_attempt_even_if_claim_cleared(monkeypatch):
    session = FakeSession(RowResult(row=None))
    install(monkeypatch, session)
    assert await SqlChannelRepository().claim_outbound(
        tenant_id=TENANT, delivery_id=DELIVERY, lease_seconds=90,
    ) is None
    sql, _ = session.calls[0]
    assert "o.attempt_count = 0" in sql
    assert "o.claim_expires_at IS NULL" in sql
    assert "u.is_verified = true" in sql


def provider_status(
    *, state=ChannelDeliveryState.DELIVERED, recipient="15551234567",
    message="wamid.live-provider", timestamp=1770000000,
):
    return ChannelProviderStatusEvent(
        connection_id="conn",
        provider_message_id=message,
        recipient_id=recipient,
        state=state,
        provider_timestamp=timestamp,
        provider_receipt_id=ChannelProviderStatusEvent.receipt_for(
            provider_message_id=message, recipient_id=recipient,
            state=state, provider_timestamp=timestamp,
        ),
        error_code="whatsapp_provider_failed" if state is ChannelDeliveryState.FAILED else None,
    )


@pytest.mark.asyncio
async def test_signed_status_insert_is_revision_bound_and_never_a_chat_or_new_send(monkeypatch):
    from ai_karen_engine.extensions.channels.contracts import ChannelConnection

    connection = ChannelConnection(
        tenant_id=TENANT, connection_id="conn",
        installation_id="whatsapp-cloud", provider_account_id="10987654321",
        credential_handle="vault://secret", revision=3, enabled=True,
    )
    session = FakeSession(RowResult(scalar="a" * 64), RowResult(scalar=None))
    install(monkeypatch, session)
    assert await SqlChannelRepository().record_provider_status(
        connection=connection, status=provider_status(),
    )
    sql, args = session.calls[0]
    assert "INSERT INTO public.channel_provider_status_events" in sql
    assert "c.enabled = true" in sql
    assert "c.revision = :revision" in sql
    assert args["tenant"] == TENANT
    assert args["revision"] == 3
    assert args["state"] == "delivered"
    assert "raw_body" not in args and "user_id" not in args
    update, params = session.calls[1]
    assert "UPDATE public.channel_outbox" in update
    assert "o.destination_id = :recipient" in update
    assert "i.connection_revision = c.revision" in update
    assert "o.claim_token IS NULL" in update
    assert "o.status = 'sent'" in update
    assert "o.status = 'delivered'" in update
    assert params["recipient"] == "15551234567"


@pytest.mark.asyncio
async def test_status_replay_checks_exact_persisted_digest_then_reconciles(monkeypatch):
    from ai_karen_engine.extensions.channels.contracts import ChannelConnection

    connection = ChannelConnection(
        tenant_id=TENANT, connection_id="conn",
        installation_id="whatsapp-cloud", provider_account_id="10987654321",
        credential_handle="vault://secret", revision=1, enabled=True,
    )
    session = FakeSession(RowResult(scalar="a" * 64), RowResult(scalar=None))
    install(monkeypatch, session)
    event = provider_status()
    assert await SqlChannelRepository().record_provider_status(
        connection=connection, status=event,
    )
    digest = session.calls[0][1]["digest"]
    session.results.extend([
        RowResult(scalar=None), RowResult(scalar=digest), RowResult(scalar=None),
    ])
    assert await SqlChannelRepository().record_provider_status(
        connection=connection, status=event,
    )
    assert "e.event_digest" in session.calls[3][0]
    assert session.calls[3][1]["digest"] == digest
    assert "UPDATE public.channel_outbox" in session.calls[4][0]


@pytest.mark.asyncio
async def test_status_replay_with_missing_connection_denied(monkeypatch):
    from ai_karen_engine.extensions.channels.contracts import ChannelConnection

    connection = ChannelConnection(
        tenant_id=TENANT, connection_id="conn",
        installation_id="whatsapp-cloud", provider_account_id="10987654321",
        credential_handle="vault://secret", revision=1, enabled=True,
    )
    session = FakeSession(RowResult(scalar=None), RowResult(scalar=None))
    install(monkeypatch, session)
    with pytest.raises(module.ChannelAdmissionDenied):
        await SqlChannelRepository().record_provider_status(
            connection=connection, status=provider_status(),
        )
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_status_receipt_forgery_and_disabled_connection_denied_before_sql(monkeypatch):
    from ai_karen_engine.extensions.channels.contracts import ChannelConnection

    connection = ChannelConnection(
        tenant_id=TENANT, connection_id="conn",
        installation_id="whatsapp-cloud", provider_account_id="10987654321",
        credential_handle="vault://secret", revision=1, enabled=False,
    )
    session = FakeSession()
    install(monkeypatch, session)
    with pytest.raises(module.ChannelAdmissionDenied):
        await SqlChannelRepository().record_provider_status(
            connection=connection, status=provider_status(),
        )
    active = connection.model_copy(update={"enabled": True})
    spoofed = provider_status().model_copy(update={"provider_receipt_id": "0" * 64})
    with pytest.raises(ValueError, match="does not match"):
        await SqlChannelRepository().record_provider_status(
            connection=active, status=spoofed,
        )
    assert not session.calls
