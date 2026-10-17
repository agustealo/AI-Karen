"""KOC-04B admission proof: identity and idempotency belong to the host store."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_karen_engine.extensions.channels.contracts import (
    ChannelConnection,
    ChannelDeliveryRequest,
    InboundChannelEvent,
)
from ai_karen_engine.persistence.repositories import channel_repository as module
from ai_karen_engine.persistence.repositories.channel_repository import (
    ChannelAdmissionConflict,
    ChannelAdmissionDenied,
    SqlChannelRepository,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_TENANT = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
INBOX = "cccccccc-cccc-cccc-cccc-cccccccccccc"
BINDING = "dddddddd-dddd-dddd-dddd-dddddddddddd"
USER = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
CORRELATION = "ffffffff-ffff-ffff-ffff-ffffffffffff"


def connection():
    return ChannelConnection(
        connection_id="connection-a",
        installation_id="plugin-a",
        tenant_id=TENANT,
        provider_account_id="account-a",
        credential_handle="vault://credential-a",
        revision=3,
        enabled=True,
    )


def native_event():
    return InboundChannelEvent(
        connection_id="connection-a",
        external_event_id="event-1",
        external_sender_id="sender-1",
        external_conversation_id="external-chat-1",
        message_kind="text",
        text="Hello Karen",
    )


def committed_row(*, digest=None):
    return {
        "inbox_id": INBOX,
        "correlation_id": CORRELATION,
        "tenant_id": TENANT,
        "user_id": USER,
        "binding_id": BINDING,
        "event_digest": digest or module._event_digest(native_event()),
    }


class FakeResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row


class FakeSession:
    def __init__(self, *rows):
        self.rows = list(rows)
        self.calls = []

    async def execute(self, statement, args):
        self.calls.append((str(statement), dict(args)))
        return FakeResult(self.rows.pop(0))


def install_scope(monkeypatch, session):
    @asynccontextmanager
    async def scope(tenant_id):
        assert tenant_id == TENANT
        yield session

    monkeypatch.setattr(module, "async_transaction_scope", scope)


@pytest.mark.asyncio
async def test_first_admission_uses_db_owned_principal_and_scoped_connection(monkeypatch):
    session = FakeSession(committed_row())
    install_scope(monkeypatch, session)

    receipt = await SqlChannelRepository().admit_verified_inbound(
        connection=connection(), event=native_event()
    )

    assert receipt.inserted is True
    assert receipt.user_id == USER
    assert receipt.binding_id == BINDING
    assert receipt.correlation_id == CORRELATION
    sql, args = session.calls[0]
    assert "INSERT INTO public.channel_inbox" in sql
    assert "JOIN public.channel_identity_bindings b" in sql
    assert "c.tenant_id = CAST(:tenant AS uuid)" in sql
    assert "c.revision = :revision" in sql
    assert "b.revoked_at IS NULL" in sql
    assert "ON CONFLICT (tenant_id, connection_id, external_event_id)" in sql
    assert "DO NOTHING" in sql
    assert args["tenant"] == TENANT
    assert args["revision"] == 3
    assert "user_id" not in args
    assert "binding_id" not in args
    assert "vault://credential-a" not in str(args)


@pytest.mark.asyncio
async def test_replayed_event_returns_original_receipt_no_second_insert(monkeypatch):
    session = FakeSession(None, committed_row())
    install_scope(monkeypatch, session)

    receipt = await SqlChannelRepository().admit_verified_inbound(
        connection=connection(), event=native_event()
    )

    assert receipt.inserted is False
    assert receipt.inbox_id == INBOX
    assert len(session.calls) == 2
    assert session.calls[1][1]["event"] == "event-1"


@pytest.mark.asyncio
async def test_reused_native_event_id_with_changed_content_fails(monkeypatch):
    session = FakeSession(None, committed_row(digest="0" * 64))
    install_scope(monkeypatch, session)

    with pytest.raises(ChannelAdmissionConflict):
        await SqlChannelRepository().admit_verified_inbound(
            connection=connection(), event=native_event()
        )


@pytest.mark.asyncio
async def test_unbound_or_revoked_sender_is_never_admitted(monkeypatch):
    session = FakeSession(None, None)
    install_scope(monkeypatch, session)

    with pytest.raises(ChannelAdmissionDenied):
        await SqlChannelRepository().admit_verified_inbound(
            connection=connection(), event=native_event()
        )


@pytest.mark.asyncio
async def test_connection_scope_mismatch_rejected_before_sql(monkeypatch):
    @asynccontextmanager
    async def cannot_reach_sql(tenant_id):
        raise AssertionError("SQL must not execute")
        yield

    monkeypatch.setattr(module, "async_transaction_scope", cannot_reach_sql)
    event = native_event().model_copy(update={"connection_id": "other-connection"})

    with pytest.raises(ChannelAdmissionDenied):
        await SqlChannelRepository().admit_verified_inbound(
            connection=connection(), event=event
        )


@pytest.mark.asyncio
async def test_disabled_connection_rejected_before_sql():
    with pytest.raises(ChannelAdmissionDenied):
        await SqlChannelRepository().admit_verified_inbound(
            connection=connection().model_copy(update={"enabled": False}),
            event=native_event(),
        )


@pytest.mark.asyncio
async def test_claim_leases_require_bounded_duration():
    for seconds in (0, -2, 3601):
        with pytest.raises(ValueError, match="lease_seconds"):
            await SqlChannelRepository().claim_inbound(
                tenant_id=TENANT, inbox_id=INBOX, lease_seconds=seconds,
            )


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class ScalarSession:
    def __init__(self, value):
        self.value = value
        self.calls = []

    async def execute(self, statement, args):
        self.calls.append((str(statement), dict(args)))
        return ScalarResult(self.value)


def delivery_request():
    return ChannelDeliveryRequest(
        delivery_id="11111111-1111-1111-1111-111111111111",
        connection_id="connection-a",
        destination_id="native-chat",
        idempotency_key="inbox-corr-1",
        message_kind="text",
        text="Canonical ChatRuntime answer",
    )


@pytest.mark.asyncio
async def test_completion_and_outbox_stage_are_one_fenced_transaction(monkeypatch):
    session = ScalarSession("11111111-1111-1111-1111-111111111111")
    install_scope(monkeypatch, session)

    committed = await SqlChannelRepository().complete_and_stage_delivery(
        tenant_id=TENANT, inbox_id=INBOX, claim_token=BINDING,
        delivery=delivery_request(),
    )

    assert committed is True
    assert len(session.calls) == 1
    sql, args = session.calls[0]
    assert "WITH completed AS" in sql
    assert "UPDATE public.channel_inbox" in sql
    assert "INSERT INTO public.channel_outbox" in sql
    assert "claim_token = CAST(:token AS uuid)" in sql
    assert "claim_expires_at > clock_timestamp()" in sql
    assert "ON CONFLICT" not in sql
    assert "'accepted'" in sql
    assert args["tenant"] == TENANT
    assert args["body"] == "Canonical ChatRuntime answer"


@pytest.mark.asyncio
async def test_lost_inbox_lease_cannot_publish_a_delivery(monkeypatch):
    session = ScalarSession(None)
    install_scope(monkeypatch, session)

    committed = await SqlChannelRepository().complete_and_stage_delivery(
        tenant_id=TENANT, inbox_id=INBOX, claim_token=BINDING,
        delivery=delivery_request(),
    )

    assert committed is False


def test_admission_digest_does_not_serialize_external_metadata():
    event = native_event()
    poisoned = event.model_copy(update={
        "provider_metadata": {
            "secret": "redacted-key",
            "user_id": "attacker-input",
        }
    })
    assert module._event_digest(event) == module._event_digest(poisoned)


def test_migration_fences_cross_tenant_foreign_keys_and_all_four_tables():
    root = Path(__file__).resolve().parents[2]
    sql = (
        root / "supabase" / "migrations" /
        "20261017010000_31_channel_gateway_durable_admission.sql"
    ).read_text()

    for table in (
        "channel_connections",
        "channel_identity_bindings",
        "channel_inbox",
        "channel_outbox",
    ):
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in sql
        assert f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;" in sql
        assert f"CREATE POLICY {table}" not in sql or "tenant_scope" in sql
    assert "FOREIGN KEY (tenant_id, connection_id, binding_id, user_id)" in sql
    assert "FOREIGN KEY (tenant_id, connection_id, inbox_id)" in sql
    assert "FOREIGN KEY (tenant_id, user_id)" in sql
    assert "UNIQUE (tenant_id, connection_id, external_event_id)" in sql
    assert "app.current_tenant_id" in sql
    assert "app.channel_worker" not in sql
