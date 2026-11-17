"""KWA-01C6C2B1: authenticated, one-use WhatsApp linking remains host owned."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from ai_karen_engine.api_routes.channels.identity import router
from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.auth.auth_service import UserStatus
from ai_karen_engine.services.channels.activation import ChannelActivationService
from ai_karen_engine.services.channels.host import ChannelHostServices
from ai_karen_engine.services.channels.linking import (
    ChannelLinkConflict,
    IssuedChannelLink,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
CONNECTION = "cccccccc-cccc-cccc-cccc-cccccccccccc"
CHALLENGE = "dddddddd-dddd-dddd-dddd-dddddddddddd"
COMMAND = "/link " + "a" * 43


@pytest.fixture
def client_and_host():
    user = SimpleNamespace(
        tenant_id=TENANT, user_id=USER, is_active=True, is_verified=True,
    )
    host = object.__new__(ChannelHostServices)
    host.activation = SimpleNamespace(
        issue_action_plan=AsyncMock(return_value=object()),
    )
    host.issue_whatsapp_self_link_challenge = AsyncMock(
        return_value=IssuedChannelLink(
            challenge_id=CHALLENGE, command=COMMAND, expires_in_seconds=600,
        ),
    )
    host.inspect_whatsapp_self_link_status = AsyncMock(return_value="pending")
    app = FastAPI()
    app.include_router(router)
    app.state.channel_host_services = host
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        yield client, host, user


def test_one_time_link_command_is_scoped_and_never_cacheable(client_and_host):
    client, host, _user = client_and_host
    response = client.post(
        f"/api/channels/identity/whatsapp/connections/{CONNECTION}/challenge",
    )
    assert response.status_code == 201
    assert response.json() == {
        "challenge_id": CHALLENGE,
        "command": COMMAND,
        "expires_in_seconds": 600,
    }
    assert "no-store" in response.headers["cache-control"]
    assert "no-cache" in response.headers["pragma"]
    kwargs = host.activation.issue_action_plan.await_args.kwargs
    assert kwargs["installation_id"] == "whatsapp-cloud"
    assert kwargs["action"] == "channel.link"
    assert kwargs["tenant_id"] == TENANT
    assert kwargs["user_id"] == USER
    assert str(UUID(kwargs["session_id"])) == kwargs["session_id"]
    assert host.issue_whatsapp_self_link_challenge.await_args.kwargs == {
        "tenant_id": TENANT,
        "user_id": USER,
        "session_id": kwargs["session_id"],
        "connection_id": CONNECTION,
        "authorized_plan": host.activation.issue_action_plan.return_value,
    }


@pytest.mark.parametrize("body", [
    {"tenant_id": "dddddddd-dddd-dddd-dddd-dddddddddddd"},
    {"user_id": "dddddddd-dddd-dddd-dddd-dddddddddddd"},
    {"proof": "attacker-controlled"},
    {"ttl_seconds": 900},
])
def test_link_ingress_never_trusts_caller_supplied_authority(client_and_host, body):
    client, host, _user = client_and_host
    response = client.post(
        f"/api/channels/identity/whatsapp/connections/{CONNECTION}/challenge",
        json=body,
    )
    assert response.status_code == 422
    host.activation.issue_action_plan.assert_not_awaited()
    host.issue_whatsapp_self_link_challenge.assert_not_awaited()


def test_link_requires_verified_user_before_minting_policy(client_and_host):
    client, host, user = client_and_host
    user.is_verified = False
    response = client.post(
        f"/api/channels/identity/whatsapp/connections/{CONNECTION}/challenge",
    )
    assert response.status_code == 403
    host.activation.issue_action_plan.assert_not_awaited()
    host.issue_whatsapp_self_link_challenge.assert_not_awaited()


@pytest.mark.parametrize("exc,status", [
    (PermissionError("vault-secret-present"), 403),
    (ChannelLinkConflict("digest-challenge-collision"), 409),
    (RuntimeError("provider-token-leaked"), 503),
])
def test_link_api_redacts_policy_and_storage_failures(client_and_host, exc, status):
    client, host, _ = client_and_host
    host.issue_whatsapp_self_link_challenge.side_effect = exc
    response = client.post(
        f"/api/channels/identity/whatsapp/connections/{CONNECTION}/challenge",
    )
    assert response.status_code == status
    assert "vault-secret" not in response.text
    assert "provider-token" not in response.text
    assert "digest-challenge" not in response.text


def test_link_unauthorized_plan_never_reaches_host(client_and_host):
    client, host, _ = client_and_host
    host.activation.issue_action_plan.side_effect = PermissionError("policy denied")
    response = client.post(
        f"/api/channels/identity/whatsapp/connections/{CONNECTION}/challenge",
    )
    assert response.status_code == 403
    host.issue_whatsapp_self_link_challenge.assert_not_awaited()


def test_link_unavailable_host_cannot_invent_success(client_and_host):
    client, host, _ = client_and_host
    host.activation = None
    response = client.post(
        f"/api/channels/identity/whatsapp/connections/{CONNECTION}/challenge",
    )
    assert response.status_code == 503
    host.issue_whatsapp_self_link_challenge.assert_not_awaited()


@pytest.mark.asyncio
async def test_host_reuses_canonical_link_service_and_transport():
    host = object.__new__(ChannelHostServices)
    host._initialized = True
    host._closed = False
    adapter = object()
    host._installed = {"whatsapp-cloud": adapter}
    host.activation = object()
    host.kernel = SimpleNamespace(
        get_channel_activation_manifest=lambda name: (
            object() if name == "whatsapp-cloud" else None
        ),
        is_canonical_channel_adapter=lambda name, value: (
            name == "whatsapp-cloud" and value is adapter
        ),
    )
    host.linking = SimpleNamespace(
        issue_challenge=AsyncMock(return_value=IssuedChannelLink(
            challenge_id=CHALLENGE, command=COMMAND, expires_in_seconds=600,
        )),
    )
    plan = object()
    result = await host.issue_whatsapp_self_link_challenge(
        tenant_id=TENANT, user_id=USER, session_id="session",
        connection_id=CONNECTION, authorized_plan=plan,
    )
    assert result.command == COMMAND
    host.linking.issue_challenge.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER, session_id="session",
        connection_id=CONNECTION, authorized_plan=plan,
    )

    host.kernel.is_canonical_channel_adapter = lambda name, value: False
    with pytest.raises(PermissionError, match="Canonical"):
        await host.issue_whatsapp_self_link_challenge(
            tenant_id=TENANT, user_id=USER, session_id="session",
            connection_id=CONNECTION, authorized_plan=plan,
        )
    host.linking.issue_challenge.assert_awaited_once()


def _status(client):
    return client.get(
        f"/api/channels/identity/whatsapp/connections/{CONNECTION}/"
        f"challenges/{CHALLENGE}/status"
    )


def test_link_status_is_caller_scoped_and_never_echoes_native_sender(client_and_host):
    client, host, _ = client_and_host
    response = _status(client)
    assert response.status_code == 200
    assert response.json() == {
        "challenge_id": CHALLENGE,
        "status": "pending",
        "evidence_basis": "host_link_challenge_ledger",
        "current_binding_verified": False,
        "delivery_verified": False,
    }
    assert "no-store" in response.headers["cache-control"]
    assert "no-cache" in response.headers["pragma"]
    assert COMMAND not in response.text
    kwargs = host.activation.issue_action_plan.await_args.kwargs
    assert kwargs["action"] == "channel.link"
    assert kwargs["tenant_id"] == TENANT
    assert kwargs["user_id"] == USER
    host.inspect_whatsapp_self_link_status.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER,
        session_id=kwargs["session_id"], connection_id=CONNECTION,
        challenge_id=CHALLENGE,
        authorized_plan=host.activation.issue_action_plan.return_value,
    )


@pytest.mark.parametrize("status", [
    "pending", "consumed", "expired", "revoked", "invalidated",
])
def test_status_represents_only_database_observation(client_and_host, status):
    client, host, _ = client_and_host
    host.inspect_whatsapp_self_link_status.return_value = status
    response = _status(client)
    assert response.status_code == 200
    assert response.json()["status"] == status
    assert response.json()["current_binding_verified"] is False
    assert response.json()["delivery_verified"] is False


def test_status_not_found_is_404_without_any_principal_leak(client_and_host):
    client, host, _ = client_and_host
    host.inspect_whatsapp_self_link_status.return_value = None
    response = _status(client)
    assert response.status_code == 404
    assert COMMAND not in response.text


@pytest.mark.parametrize("status", ["linked_live", "meta_verified", True, 2])
def test_unknown_backend_status_fails_closed(client_and_host, status):
    client, host, _ = client_and_host
    host.inspect_whatsapp_self_link_status.return_value = status
    response = _status(client)
    assert response.status_code == 503
    assert str(status) not in response.text


def test_link_status_requires_verified_actor_and_plan(client_and_host):
    client, host, user = client_and_host
    user.is_verified = False
    response = _status(client)
    assert response.status_code == 403
    host.activation.issue_action_plan.assert_not_awaited()
    host.inspect_whatsapp_self_link_status.assert_not_awaited()


def test_status_policy_denial_blocks_host_inspection(client_and_host):
    client, host, _ = client_and_host
    host.activation.issue_action_plan.side_effect = PermissionError("secret")
    response = _status(client)
    assert response.status_code == 403
    assert "secret" not in response.text
    host.inspect_whatsapp_self_link_status.assert_not_awaited()


def test_status_uses_no_client_identity_or_mutating_body(client_and_host):
    client, host, _ = client_and_host
    for invalid_url in (
        f"/api/channels/identity/whatsapp/connections/not-a-uuid/challenges/{CHALLENGE}/status",
        f"/api/channels/identity/whatsapp/connections/{CONNECTION}/challenges/nope/status",
    ):
        assert client.get(invalid_url).status_code == 422
    host.inspect_whatsapp_self_link_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_host_status_checks_canonical_adapter_and_runtime_gate_first():
    host = object.__new__(ChannelHostServices)
    host._initialized = True
    host._closed = False
    canonical = object()
    host._installed = {"whatsapp-cloud": canonical}
    host.activation = SimpleNamespace(_authorize=AsyncMock())
    host.kernel = SimpleNamespace(
        get_channel_activation_manifest=lambda _: object(),
        is_canonical_channel_adapter=lambda _, adapter: adapter is canonical,
    )
    host.repository = SimpleNamespace(
        inspect_link_challenge_status=AsyncMock(return_value="consumed"),
    )
    plan = SimpleNamespace(policy_decision_id="policy-proven")
    result = await host.inspect_whatsapp_self_link_status(
        tenant_id=TENANT, user_id=USER, session_id="actual-session",
        connection_id=CONNECTION, challenge_id=CHALLENGE,
        authorized_plan=plan,
    )
    assert result == "consumed"
    assert host.activation._authorize.await_args.kwargs["action"] == "channel.link"
    assert host.activation._authorize.await_args.kwargs["plan"] is plan
    host.repository.inspect_link_challenge_status.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER,
        connection_id=CONNECTION, challenge_id=CHALLENGE,
    )
    host.activation._authorize.side_effect = PermissionError("policy-denied")
    with pytest.raises(PermissionError):
        await host.inspect_whatsapp_self_link_status(
            tenant_id=TENANT, user_id=USER, session_id="actual-session",
            connection_id=CONNECTION, challenge_id=CHALLENGE,
            authorized_plan=plan,
        )
    host.repository.inspect_link_challenge_status.assert_awaited_once()


def _service(role: str) -> ChannelActivationService:
    principal = SimpleNamespace(
        id=USER, tenant_id=TENANT, status=UserStatus.ACTIVE,
        is_verified=True, roles=[role],
    )
    catalog = SimpleNamespace(
        capabilities=SimpleNamespace(communication_channel=object()),
        rbac=SimpleNamespace(allowed_roles=["admin"]),
    )
    kernel = SimpleNamespace(
        get_catalog_manifest=lambda _: catalog,
        get_record=lambda _: {"is_valid": True},
        get_channel_activation_manifest=lambda _: catalog,
    )
    return ChannelActivationService(
        kernel=kernel,
        repository=SimpleNamespace(),
        principal_lookup=AsyncMock(return_value=principal),
    )


@pytest.mark.asyncio
async def test_verified_user_self_link_gets_only_own_action_plan():
    service = _service("user")
    plan = await service.issue_action_plan(
        tenant_id=TENANT, user_id=USER, session_id="user-session",
        installation_id="whatsapp-cloud", action="channel.link",
    )
    assert plan.allowed_capabilities == ["channel.link"]
    assert plan.allowed_plugins == ["whatsapp-cloud"]
    with pytest.raises(PermissionError):
        await service.issue_action_plan(
            tenant_id=TENANT, user_id=USER, session_id="user-session",
            installation_id="whatsapp-cloud", action="channel.provision",
        )


@pytest.mark.asyncio
async def test_canonical_admin_rbac_controls_all_existing_whatsapp_actions():
    permissions_path = (
        Path(__file__).resolve().parents[2] / "config_assets" / "permissions.json"
    )
    config = json.loads(permissions_path.read_text(encoding="utf-8"))
    admin = config["role_permissions"]["admin"]["permissions"]
    user = config["role_permissions"]["user"]["permissions"]
    governed_actions = {
        "channel.provision", "channel.activate", "channel.deactivate",
        "channel.recover", "channel.send", "channel.inspect",
        "channel.webhook.register", "channel.status_prune", "channel.link",
    }
    assert governed_actions.issubset(admin)
    assert "channel.link" in user
    assert "channel.provision" not in user
    assert "channel.send" not in user
    for action in governed_actions:
        assert Permission(action) in get_rbac_manager().get_user_permissions({
            "user_id": USER, "tenant_id": TENANT, "roles": ["admin"],
        })
    assert Permission.CHANNEL_LINK in get_rbac_manager().get_user_permissions({
        "user_id": USER, "tenant_id": TENANT, "roles": ["user"],
    })
