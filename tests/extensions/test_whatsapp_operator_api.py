"""Authenticated WhatsApp operator actions delegate to governed host authority.

No test response ever implies a Meta webhook, signed inbound, or delivery
receipt. Host-side callers must still prove Vault and Graph identity.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from ai_karen_engine.api_routes.channels.operator import router
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.extensions.channels.contracts import ChannelConnection
from ai_karen_engine.services.channels.activation import ChannelActivationConflict
from ai_karen_engine.services.channels.host import ChannelHostServices

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
CONNECTION = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _connection(*, enabled: bool, revision: int, tenant_id: str = TENANT):
    return ChannelConnection(
        tenant_id=tenant_id,
        connection_id=CONNECTION,
        installation_id="whatsapp-cloud",
        provider_account_id="30987654321",
        credential_handle="vault://scoped-wa",
        enabled=enabled,
        revision=revision,
    )


@pytest.fixture
def operator_api():
    user = SimpleNamespace(
        tenant_id=TENANT, user_id=USER, is_active=True, is_verified=True
    )
    host = object.__new__(ChannelHostServices)
    host.activation = SimpleNamespace(issue_action_plan=AsyncMock(return_value=object()))
    host.list_whatsapp_operator_connections = AsyncMock(
        return_value=[
            {"connection_id": CONNECTION, "connection_revision": 1, "enabled": False}
        ]
    )
    host.provision_whatsapp_connection = AsyncMock(
        return_value=_connection(enabled=False, revision=1)
    )
    host.activate_whatsapp_connection = AsyncMock(
        return_value=_connection(enabled=True, revision=2)
    )
    host.deactivate_whatsapp_connection = AsyncMock(
        return_value=_connection(enabled=False, revision=3)
    )
    app = FastAPI()
    app.include_router(router)
    app.state.channel_host_services = host
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        yield client, host, user


def test_operator_provisions_and_activates_without_fabricating_webhook_proof(operator_api):
    client, host, _user = operator_api
    response = client.post(
        "/api/channels/operator/whatsapp/connections",
        json={"provider_account_id": "30987654321", "credential_handle": "vault://scoped-wa"},
    )
    assert response.status_code == 201
    assert response.json() == {
        "connection_id": CONNECTION,
        "connection_revision": 1,
        "enabled": False,
        "stage": "provisioned",
        "provider_phone_verified": False,
        "webhook_subscription_verified": False,
        "signed_inbound_verified": False,
        "delivery_verified": False,
    }
    kwargs = host.provision_whatsapp_connection.await_args.kwargs
    assert kwargs["tenant_id"] == TENANT
    assert kwargs["user_id"] == USER
    assert kwargs["provider_account_id"] == "30987654321"
    assert kwargs["credential_handle"] == "vault://scoped-wa"
    assert str(UUID(kwargs["session_id"])) == kwargs["session_id"]
    assert host.activation.issue_action_plan.await_args.kwargs["action"] == "channel.provision"

    response = client.post(
        f"/api/channels/operator/whatsapp/connections/{CONNECTION}/activate",
        json={"expected_revision": 1},
    )
    assert response.status_code == 200
    assert response.json() == {
        "connection_id": CONNECTION,
        "connection_revision": 2,
        "enabled": True,
        "stage": "activated",
        "provider_phone_verified": True,
        "webhook_subscription_verified": False,
        "signed_inbound_verified": False,
        "delivery_verified": False,
    }
    host.activate_whatsapp_connection.assert_awaited_once()
    assert host.activate_whatsapp_connection.await_args.kwargs["expected_revision"] == 1
    assert host.activation.issue_action_plan.await_args.kwargs["action"] == "channel.activate"

    response = client.post(
        f"/api/channels/operator/whatsapp/connections/{CONNECTION}/deactivate",
        json={"expected_revision": 2},
    )
    assert response.status_code == 200
    assert response.json()["stage"] == "deactivated"
    assert response.json()["enabled"] is False
    assert response.json()["delivery_verified"] is False
    assert host.deactivate_whatsapp_connection.await_args.kwargs["expected_revision"] == 2
    assert host.activation.issue_action_plan.await_args.kwargs["action"] == "channel.deactivate"


@pytest.mark.parametrize("payload", [
    {"provider_account_id": "30987654321", "credential_handle": "vault://wa", "tenant_id": TENANT},
    {"provider_account_id": "30987654321", "credential_handle": "vault://wa", "access_token": "forbidden"},
    {"provider_account_id": "wa", "credential_handle": "vault://wa"},
])
def test_operator_rejects_forged_identity_and_credential_fields(operator_api, payload):
    client, host, _ = operator_api
    response = client.post("/api/channels/operator/whatsapp/connections", json=payload)
    assert response.status_code == 422
    host.provision_whatsapp_connection.assert_not_awaited()
    host.activation.issue_action_plan.assert_not_awaited()


@pytest.mark.parametrize("payload", [
    {"expected_revision": 0},
    {"expected_revision": True},
    {"expected_revision": 1, "role": "admin"},
    {"expected_revision": 1, "authorized_plan": {"allowed_plugins": ["whatsapp-cloud"]}},
])
def test_operator_rejects_invalid_revisions_and_forged_plans(operator_api, payload):
    client, host, _ = operator_api
    response = client.post(
        f"/api/channels/operator/whatsapp/connections/{CONNECTION}/activate",
        json=payload,
    )
    assert response.status_code == 422
    host.activate_whatsapp_connection.assert_not_awaited()
    host.activation.issue_action_plan.assert_not_awaited()


def test_operator_denies_unverified_actor_before_runtime_policy(operator_api):
    client, host, user = operator_api
    user.is_verified = False
    response = client.post(
        "/api/channels/operator/whatsapp/connections",
        json={"provider_account_id": "30987654321", "credential_handle": "vault://wa"},
    )
    assert response.status_code == 403
    host.activation.issue_action_plan.assert_not_awaited()
    host.provision_whatsapp_connection.assert_not_awaited()


def test_policy_denial_cannot_provision_or_start_transport(operator_api):
    client, host, _ = operator_api
    host.activation.issue_action_plan.side_effect = PermissionError("RBAC denied")
    response = client.post(
        f"/api/channels/operator/whatsapp/connections/{CONNECTION}/activate",
        json={"expected_revision": 1},
    )
    assert response.status_code == 403
    assert "RBAC" not in response.text
    host.activate_whatsapp_connection.assert_not_awaited()


def test_stale_activation_revision_is_conflict_without_secret_leak(operator_api):
    client, host, _ = operator_api
    host.activate_whatsapp_connection.side_effect = ChannelActivationConflict(
        "stale vault://scoped-wa provider account"
    )
    response = client.post(
        f"/api/channels/operator/whatsapp/connections/{CONNECTION}/activate",
        json={"expected_revision": 1},
    )
    assert response.status_code == 409
    assert "vault://" not in response.text
    assert "provider account" not in response.text


def test_operator_never_claims_cross_tenant_provision_success(operator_api):
    client, host, _ = operator_api
    host.provision_whatsapp_connection.return_value = _connection(
        enabled=False, revision=1,
        tenant_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
    )
    response = client.post(
        "/api/channels/operator/whatsapp/connections",
        json={"provider_account_id": "30987654321", "credential_handle": "vault://wa"},
    )
    assert response.status_code == 503
    assert "tenant" not in response.text.lower()


def test_operator_host_missing_is_unavailable_not_fake_success(operator_api):
    client, host, _ = operator_api
    host.activation = None
    response = client.post(
        "/api/channels/operator/whatsapp/connections",
        json={"provider_account_id": "30987654321", "credential_handle": "vault://wa"},
    )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_host_uses_canonical_loaded_whatsapp_adapter_for_lifecycle():
    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan

    adapter = object()
    plan = AuthorizedExecutionPlan(
        execution_id="operator-exec",
        policy_decision_id="operator-policy",
        authorized_user_id=USER,
        authorized_tenant_id=TENANT,
        authorized_session_id="session-verified",
        allowed_plugins=["whatsapp-cloud"],
        allowed_capabilities=[
            "channel.provision", "channel.activate", "channel.deactivate",
        ],
    )
    host = object.__new__(ChannelHostServices)
    host._initialized = True
    host._closed = False
    host._installed = {"whatsapp-cloud": adapter}
    host.kernel = SimpleNamespace(
        get_channel_activation_manifest=lambda name: object(),
        is_canonical_channel_adapter=lambda name, candidate: (
            name == "whatsapp-cloud" and candidate is adapter
        ),
    )
    host.repository = SimpleNamespace(
        get_connection=AsyncMock(return_value=_connection(enabled=False, revision=1))
    )
    host.activation = SimpleNamespace(
        provision=AsyncMock(return_value=_connection(enabled=False, revision=1)),
        activate=AsyncMock(return_value=_connection(enabled=True, revision=2)),
        deactivate=AsyncMock(return_value=_connection(enabled=False, revision=3)),
    )

    prepared = await host.provision_whatsapp_connection(
        tenant_id=TENANT, user_id=USER, session_id="session-verified",
        provider_account_id="30987654321",
        credential_handle="vault://scoped-wa", authorized_plan=plan,
    )
    assert not prepared.enabled
    assert host.activation.provision.await_args.kwargs["installation_id"] == "whatsapp-cloud"
    assert host.activation.provision.await_args.kwargs["authorized_plan"] is plan

    activated = await host.activate_whatsapp_connection(
        tenant_id=TENANT, connection_id=CONNECTION, user_id=USER,
        session_id="session-verified", authorized_plan=plan,
        expected_revision=1,
    )
    assert activated.enabled
    assert host.activation.activate.await_args.kwargs["adapter"] is adapter
    assert host.activation.activate.await_args.kwargs["expected_revision"] == 1
    assert host.activation.activate.await_args.kwargs["settings"] == {
        "private_text_only": True
    }

    host.repository.get_connection.return_value = activated
    deactivated = await host.deactivate_whatsapp_connection(
        tenant_id=TENANT, connection_id=CONNECTION, user_id=USER,
        session_id="session-verified", authorized_plan=plan,
        expected_revision=2,
    )
    assert not deactivated.enabled
    assert host.activation.deactivate.await_args.kwargs["adapter"] is adapter
    assert host.activation.deactivate.await_args.kwargs["expected_revision"] == 2


@pytest.mark.asyncio
async def test_host_never_executes_stale_or_foreign_whatsapp_connection():
    adapter = object()
    host = object.__new__(ChannelHostServices)
    host._initialized = True
    host._closed = False
    host._installed = {"whatsapp-cloud": adapter}
    host.kernel = SimpleNamespace(
        get_channel_activation_manifest=lambda name: object(),
        is_canonical_channel_adapter=lambda name, candidate: candidate is adapter,
    )
    host.repository = SimpleNamespace(
        get_connection=AsyncMock(return_value=_connection(enabled=False, revision=2))
    )
    host.activation = SimpleNamespace(activate=AsyncMock(), deactivate=AsyncMock())
    args = {
        "tenant_id": TENANT, "connection_id": CONNECTION, "user_id": USER,
        "session_id": "session-verified", "authorized_plan": object(),
        "expected_revision": 1,
    }
    with pytest.raises(ChannelActivationConflict):
        await host.activate_whatsapp_connection(**args)
    host.activation.activate.assert_not_awaited()

    host.repository.get_connection.return_value = _connection(
        enabled=False, revision=1,
        tenant_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
    )
    with pytest.raises(PermissionError):
        await host.activate_whatsapp_connection(**args)
    host.activation.activate.assert_not_awaited()

    host.repository.get_connection.return_value = _connection(
        enabled=True, revision=3,
    )
    with pytest.raises(ChannelActivationConflict):
        await host.deactivate_whatsapp_connection(**{**args, "expected_revision": 2})
    host.activation.deactivate.assert_not_awaited()


def test_authenticated_operator_inventory_uses_fresh_inspect_policy(operator_api):
    client, host, _ = operator_api
    response = client.get("/api/channels/operator/whatsapp/connections")
    assert response.status_code == 200
    assert response.json() == {
        "connections": [{
            "connection_id": CONNECTION, "connection_revision": 1,
            "enabled": False,
        }],
    }
    plan_kwargs = host.activation.issue_action_plan.await_args.kwargs
    assert plan_kwargs["action"] == "channel.inspect"
    assert plan_kwargs["tenant_id"] == TENANT
    assert plan_kwargs["user_id"] == USER
    assert host.list_whatsapp_operator_connections.await_args.kwargs == {
        "tenant_id": TENANT,
        "user_id": USER,
        "session_id": plan_kwargs["session_id"],
        "authorized_plan": host.activation.issue_action_plan.return_value,
    }
    assert "credential_handle" not in response.text
    assert "provider_account_id" not in response.text


def test_operator_inventory_denies_unverified_actor_without_database_read(operator_api):
    client, host, user = operator_api
    user.is_verified = False
    response = client.get("/api/channels/operator/whatsapp/connections")
    assert response.status_code == 403
    host.activation.issue_action_plan.assert_not_awaited()
    host.list_whatsapp_operator_connections.assert_not_awaited()


def test_operator_inventory_policy_denial_does_not_call_host_listing(operator_api):
    client, host, _ = operator_api
    host.activation.issue_action_plan.side_effect = PermissionError("not operator")
    response = client.get("/api/channels/operator/whatsapp/connections")
    assert response.status_code == 403
    host.list_whatsapp_operator_connections.assert_not_awaited()


def test_operator_inventory_fails_closed_when_host_returns_secrets(operator_api):
    client, host, _ = operator_api
    host.list_whatsapp_operator_connections.return_value = [{
        "connection_id": CONNECTION, "connection_revision": 1,
        "enabled": False, "credential_handle": "vault://never-serialize",
    }]
    response = client.get("/api/channels/operator/whatsapp/connections")
    assert response.status_code == 503
    assert "vault://" not in response.text


@pytest.mark.asyncio
async def test_host_inventory_gate_must_authorize_before_repository_read():
    adapter = object()
    host = object.__new__(ChannelHostServices)
    host._initialized = True
    host._closed = False
    host._installed = {"whatsapp-cloud": adapter}
    host.kernel = SimpleNamespace(
        get_channel_activation_manifest=lambda _name: object(),
        is_canonical_channel_adapter=lambda name, instance: (
            name == "whatsapp-cloud" and instance is adapter
        ),
    )
    host.activation = SimpleNamespace(_authorize=AsyncMock())
    host.repository = SimpleNamespace(
        list_whatsapp_operator_connections=AsyncMock(return_value=[])
    )
    plan = object()
    result = await host.list_whatsapp_operator_connections(
        tenant_id=TENANT, user_id=USER, session_id="scoped-session",
        authorized_plan=plan,
    )
    assert result == []
    host.activation._authorize.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER, session_id="scoped-session",
        installation_id="whatsapp-cloud", action="channel.inspect", plan=plan,
    )
    host.repository.list_whatsapp_operator_connections.assert_awaited_once_with(
        tenant_id=TENANT,
    )
    host.activation._authorize.side_effect = PermissionError("rbac")
    with pytest.raises(PermissionError):
        await host.list_whatsapp_operator_connections(
            tenant_id=TENANT, user_id=USER,
            session_id="scoped-session", authorized_plan=plan,
        )
    assert host.repository.list_whatsapp_operator_connections.await_count == 1
