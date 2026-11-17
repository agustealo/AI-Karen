"""KWA-01C6C2C1: inspect actual persisted WhatsApp lineage, never invent Meta proof."""
from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from ai_karen_engine.api_routes.channels.operator import router
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.persistence.repositories import channel_repository as module
from ai_karen_engine.persistence.repositories.channel_repository import (
    SqlChannelRepository, WhatsAppTrialEvidence,
)
from ai_karen_engine.services.channels.host import ChannelHostServices

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
CONNECTION = "cccccccc-cccc-cccc-cccc-cccccccccccc"
INBOX = "dddddddd-dddd-dddd-dddd-dddddddddddd"
CORRELATION = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
DELIVERY = "ffffffff-ffff-ffff-ffff-ffffffffffff"
EVENT = "wamid.inbound-real-event"
PROVIDER_MESSAGE = "wamid.actual-outbound-sent"
RECIPIENT = "15551234567"


class Result:
    def __init__(self, *, row=None, rows=None):
        self.row = row
        self.rows = [] if rows is None else rows

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row

    def all(self):
        return self.rows


class Session:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    async def execute(self, stmt, params):
        self.calls.append((str(stmt), dict(params)))
        return self.results.pop(0)


def install_scope(monkeypatch, session):
    @asynccontextmanager
    async def scope(tenant):
        assert tenant == TENANT
        yield session

    monkeypatch.setattr(module, "async_transaction_scope", scope)


def origin(*, status="completed", active=True):
    return {
        "inbox_id": INBOX,
        "correlation_id": CORRELATION,
        "inbox_status": status,
        "connection_revision": 4,
        "current_connection_revision": 4,
        "connection_enabled": True,
        "binding_currently_active": active,
    }


def outbound(*, status="read"):
    return {
        "delivery_id": DELIVERY,
        "status": status,
        "provider_message_id": PROVIDER_MESSAGE,
        "destination_id": RECIPIENT,
    }


def trial():
    return WhatsAppTrialEvidence(
        connection_revision=4,
        current_connection_revision=4,
        connection_enabled=True,
        inbox_id=INBOX,
        correlation_id=CORRELATION,
        inbox_status="completed",
        binding_currently_active=True,
        outbound_delivery_id=DELIVERY,
        outbound_status="read",
        outbound_provider_message_sha256=hashlib.sha256(
            PROVIDER_MESSAGE.encode()
        ).hexdigest(),
        provider_receipt_states=("delivered", "read"),
    )


@pytest.mark.asyncio
async def test_trial_read_joins_exact_tenant_inbound_binding_outbox_and_status(monkeypatch):
    session = Session(
        Result(row=origin()),
        Result(rows=[outbound()]),
        Result(rows=[{"state": "read"}, {"state": "delivered"}]),
    )
    install_scope(monkeypatch, session)
    evidence = await SqlChannelRepository().inspect_whatsapp_trial(
        tenant_id=TENANT, connection_id=CONNECTION, external_event_id=EVENT,
    )
    assert evidence == trial()
    assert len(session.calls) == 3
    sql, args = session.calls[0]
    assert "public.channel_inbox i" in sql
    assert "JOIN public.channel_connections c" in sql
    assert "JOIN public.channel_identity_bindings b" in sql
    assert "c.installation_id = 'whatsapp-cloud'" in sql
    assert "b.binding_id = i.binding_id" in sql
    assert "b.user_id = i.user_id" in sql
    assert "b.external_sender_id = i.external_sender_id" in sql
    assert "i.tenant_id = CAST(:tenant AS uuid)" in sql
    assert "i.connection_id = :connection" in sql
    assert "i.external_event_id = :event" in sql
    assert "i.provider_event_at IS NOT NULL" in sql
    assert "i.message_text" not in sql
    assert args == {"tenant": TENANT, "connection": CONNECTION, "event": EVENT}
    outbox_sql, outbox_args = session.calls[1]
    assert "public.channel_outbox o" in outbox_sql
    assert "o.tenant_id = CAST(:tenant AS uuid)" in outbox_sql
    assert "o.inbox_id = CAST(:inbox AS uuid)" in outbox_sql
    assert outbox_args["inbox"] == INBOX
    status_sql, status_args = session.calls[2]
    assert "public.channel_provider_status_events s" in status_sql
    assert "s.connection_revision = :revision" in status_sql
    assert "s.recipient_id = :recipient" in status_sql
    assert status_args == {
        "tenant": TENANT,
        "connection": CONNECTION,
        "revision": 4,
        "provider_message": PROVIDER_MESSAGE,
        "recipient": RECIPIENT,
    }
    # Only a digest, never native IDs, phone numbers, or body text.
    public = str(asdict(evidence))
    assert PROVIDER_MESSAGE not in public
    assert RECIPIENT not in public
    assert EVENT not in public


@pytest.mark.asyncio
async def test_missing_or_foreign_trial_is_missing_not_accepted(monkeypatch):
    session = Session(Result(row=None))
    install_scope(monkeypatch, session)
    assert await SqlChannelRepository().inspect_whatsapp_trial(
        tenant_id=TENANT, connection_id=CONNECTION, external_event_id=EVENT,
    ) is None
    assert len(session.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("event", [
    "", "wamid.", "not-wamid.012", "wamid./../ space",
    "wamid.\nCRLF", "wamid." + "x" * 300,
])
async def test_bad_message_id_never_reaches_db(monkeypatch, event):
    session = Session()
    install_scope(monkeypatch, session)
    with pytest.raises(ValueError):
        await SqlChannelRepository().inspect_whatsapp_trial(
            tenant_id=TENANT, connection_id=CONNECTION, external_event_id=event,
        )
    assert session.calls == []


@pytest.mark.asyncio
async def test_trial_without_outbox_cannot_claim_runtime_or_delivery(monkeypatch):
    session = Session(Result(row=origin(status="pending", active=False)), Result(rows=[]))
    install_scope(monkeypatch, session)
    evidence = await SqlChannelRepository().inspect_whatsapp_trial(
        tenant_id=TENANT, connection_id=CONNECTION, external_event_id=EVENT,
    )
    assert evidence is not None
    assert evidence.inbox_status == "pending"
    assert evidence.binding_currently_active is False
    assert evidence.outbound_delivery_id is None
    assert evidence.outbound_status is None
    assert evidence.provider_receipt_states == ()
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_trial_rejects_ambiguous_outbox_not_pick_best(monkeypatch):
    session = Session(
        Result(row=origin()),
        Result(rows=[outbound(), outbound(status="sent")]),
    )
    install_scope(monkeypatch, session)
    with pytest.raises(RuntimeError, match="Ambiguous"):
        await SqlChannelRepository().inspect_whatsapp_trial(
            tenant_id=TENANT, connection_id=CONNECTION, external_event_id=EVENT,
        )


@pytest.mark.asyncio
async def test_outbox_cannot_imply_completed_runtime_when_inbox_pending(monkeypatch):
    session = Session(
        Result(row=origin(status="processing")),
        Result(rows=[outbound(status="sent")]),
        Result(rows=[]),
    )
    install_scope(monkeypatch, session)
    with pytest.raises(RuntimeError, match="lacks completed"):
        await SqlChannelRepository().inspect_whatsapp_trial(
            tenant_id=TENANT, connection_id=CONNECTION, external_event_id=EVENT,
        )


@pytest.mark.asyncio
async def test_status_evidence_must_be_bounded_and_known(monkeypatch):
    for statuses, expected in [
        ([{"state": "unrecognized"}], "Invalid"),
        ([{"state": "delivered"}] * 101, "exceeded"),
    ]:
        session = Session(
            Result(row=origin()),
            Result(rows=[outbound()]),
            Result(rows=statuses),
        )
        install_scope(monkeypatch, session)
        with pytest.raises(RuntimeError, match=expected):
            await SqlChannelRepository().inspect_whatsapp_trial(
                tenant_id=TENANT, connection_id=CONNECTION, external_event_id=EVENT,
            )


@pytest.fixture
def api_client():
    host = object.__new__(ChannelHostServices)
    user = SimpleNamespace(
        tenant_id=TENANT, user_id=USER, is_active=True, is_verified=True,
    )
    host.activation = SimpleNamespace(
        issue_action_plan=AsyncMock(return_value=SimpleNamespace(
            policy_decision_id="test-inspect-policy",
        )),
    )
    host.inspect_whatsapp_trial_evidence = AsyncMock(return_value=trial())
    app = FastAPI()
    app.include_router(router)
    app.state.channel_host_services = host
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        yield client, host, user


def _request(client, data=None):
    return client.post(
        f"/api/channels/operator/whatsapp/connections/{CONNECTION}/trial-evidence",
        json=data if data is not None else {"external_event_id": EVENT},
    )


def test_operator_trial_endpoint_is_policy_authorized_and_redacts_sensitive_id(api_client):
    client, host, user = api_client
    response = _request(client)
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert response.json() == {
        **asdict(trial()),
        "provider_receipt_states": ["delivered", "read"],
        "evidence_basis": "host_persisted_lineage_only",
        "meta_origin_independently_verified": False,
        "consumer_certified": False,
    }
    assert PROVIDER_MESSAGE not in response.text
    assert EVENT not in response.text
    assert RECIPIENT not in response.text
    policy = host.activation.issue_action_plan.await_args.kwargs
    assert policy["action"] == "channel.inspect"
    assert policy["tenant_id"] == TENANT
    assert policy["user_id"] == USER
    host.inspect_whatsapp_trial_evidence.assert_awaited_once_with(
        tenant_id=TENANT,
        user_id=USER,
        session_id=policy["session_id"],
        connection_id=CONNECTION,
        external_event_id=EVENT,
        authorized_plan=host.activation.issue_action_plan.return_value,
    )


@pytest.mark.parametrize("payload", [
    {"external_event_id": "not-a-whatsapp-id"},
    {"external_event_id": EVENT, "tenant_id": "forged"},
    {"external_event_id": EVENT, "user_id": "forged"},
    {"external_event_id": EVENT, "authorized_plan": {"channel.inspect": True}},
    {"external_event_id": EVENT, "include_message_text": True},
])
def test_trial_rejects_untrusted_request_fields_before_policy(api_client, payload):
    client, host, _ = api_client
    response = _request(client, payload)
    assert response.status_code == 422
    host.activation.issue_action_plan.assert_not_awaited()
    host.inspect_whatsapp_trial_evidence.assert_not_awaited()


def test_trial_unverified_actor_denied_before_policy(api_client):
    client, host, user = api_client
    user.is_verified = False
    response = _request(client)
    assert response.status_code == 403
    host.activation.issue_action_plan.assert_not_awaited()
    host.inspect_whatsapp_trial_evidence.assert_not_awaited()


def test_trial_policy_denial_prevents_repository_access(api_client):
    client, host, _ = api_client
    host.activation.issue_action_plan.side_effect = PermissionError("vault://secret")
    response = _request(client)
    assert response.status_code == 403
    host.inspect_whatsapp_trial_evidence.assert_not_awaited()
    assert "vault://secret" not in response.text


def test_trial_unknown_event_returns_404_not_fake_empty_success(api_client):
    client, host, _ = api_client
    host.inspect_whatsapp_trial_evidence.return_value = None
    response = _request(client)
    assert response.status_code == 404
    assert "persisted WhatsApp trial evidence" in response.text


def test_trial_invalid_backend_data_is_not_returned(api_client):
    client, host, _ = api_client
    poisoned = SimpleNamespace(**{
        **asdict(trial()),
        "outbound_status": "delivered",
        "provider_receipt_states": ("admin-secret-token",),
    })
    host.inspect_whatsapp_trial_evidence.return_value = poisoned
    response = _request(client)
    assert response.status_code == 503
    assert "admin-secret-token" not in response.text


@pytest.mark.asyncio
async def test_host_uses_fresh_inspect_gate_before_tenant_repository_read():
    host = object.__new__(ChannelHostServices)
    host._initialized = True
    host._closed = False
    adapter = object()
    host._installed = {"whatsapp-cloud": adapter}
    host.kernel = SimpleNamespace(
        get_channel_activation_manifest=lambda _: object(),
        is_canonical_channel_adapter=lambda _, actual: actual is adapter,
    )
    host.activation = SimpleNamespace(_authorize=AsyncMock())
    host.repository = SimpleNamespace(
        inspect_whatsapp_trial=AsyncMock(return_value=trial()),
    )
    plan = SimpleNamespace(policy_decision_id="approved-inspection")
    await host.inspect_whatsapp_trial_evidence(
        tenant_id=TENANT, connection_id=CONNECTION,
        external_event_id=EVENT, user_id=USER,
        session_id="verified-session", authorized_plan=plan,
    )
    host.activation._authorize.assert_awaited_once()
    assert host.activation._authorize.await_args.kwargs["action"] == "channel.inspect"
    host.repository.inspect_whatsapp_trial.assert_awaited_once_with(
        tenant_id=TENANT, connection_id=CONNECTION, external_event_id=EVENT,
    )
    host.activation._authorize.side_effect = PermissionError("Denied")
    with pytest.raises(PermissionError):
        await host.inspect_whatsapp_trial_evidence(
            tenant_id=TENANT, connection_id=CONNECTION,
            external_event_id=EVENT, user_id=USER,
            session_id="verified-session", authorized_plan=plan,
        )
    host.repository.inspect_whatsapp_trial.assert_awaited_once()
