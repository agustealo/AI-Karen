"""Self-service QR risk consent API: authenticated owner, no fake pairing."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from pydantic import ValidationError

from ai_karen_engine.api_routes.channels import personal_consent as api
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.extensions.channels.contracts import ChannelConnection
from ai_karen_engine.services.channels.host import ChannelHostServices

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
CONNECTION = "cccccccc-cccc-cccc-cccc-cccccccccccc"
PROVIDER = "approved-managed-operator"


def actor(**changes):
    info = dict(user_id=USER, tenant_id=TENANT, roles=["user"],
                is_active=True, is_verified=True)
    info.update(changes)
    return UserData(**info)


def host_context(*, owner=True):
    host = object.__new__(ChannelHostServices)
    host.activation = SimpleNamespace(issue_action_plan=AsyncMock(return_value="trusted-plan"))
    host.settings = SimpleNamespace(
        personal_pairing_providers={"whatsapp-cloud": PROVIDER},
        installations={"whatsapp-cloud": frozenset({"pairing_webhook_secret"})},
    )
    host.repository = SimpleNamespace(
        get_connection=AsyncMock(return_value=ChannelConnection(
            connection_id=CONNECTION, tenant_id=TENANT,
            installation_id="whatsapp-cloud", provider_account_id="account",
            credential_handle="vault://ref", revision=1, enabled=False,
        )),
        is_personal_connection_owner=AsyncMock(return_value=owner),
    )
    host.get_personal_pairing_risk = AsyncMock(return_value=None)
    host.get_personal_pairing_status = AsyncMock(return_value={
        "availability": "unavailable", "last_observed_phase": None,
        "live_connected": False, "qr_available": False,
        "provider_unlinked": False,
    })
    host.acknowledge_personal_pairing_risk = AsyncMock(return_value=True)
    host.revoke_personal_pairing_risk = AsyncMock(return_value=True)
    return host, SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        channel_host_services=host,
    )))


@pytest.mark.asyncio
async def test_self_consent_mints_fresh_server_plan_without_accepting_actor_claims():
    host, request = host_context()
    result = await api.acknowledge_personal_whatsapp_risk(
        connection_id=api.UUID(CONNECTION), provider_id=PROVIDER,
        payload=api.RiskAcknowledgement(
            accepted=True, policy_version=api.PERSONAL_WHATSAPP_CONSENT_VERSION,
        ),
        request=request, user=actor(),
    )
    assert result.acknowledged is True and result.paired is False
    host.activation.issue_action_plan.assert_awaited_once()
    auth = host.activation.issue_action_plan.await_args.kwargs
    assert auth["tenant_id"] == TENANT and auth["user_id"] == USER
    assert auth["action"] == "channel.consent"
    assert auth["session_id"]
    sent = host.acknowledge_personal_pairing_risk.await_args.kwargs
    assert sent["authorized_plan"] == "trusted-plan"
    assert sent["session_id"] == auth["session_id"]
    assert sent["user_id"] == USER


@pytest.mark.asyncio
async def test_revoke_does_not_claim_unlink_or_provider_deletion():
    host, request = host_context()
    result = await api.revoke_personal_whatsapp_risk(
        connection_id=api.UUID(CONNECTION), provider_id=PROVIDER,
        request=request, user=actor(),
    )
    assert result.revoked is True
    assert result.paired is False
    assert result.provider_unlinked is False
    host.revoke_personal_pairing_risk.assert_awaited_once()


@pytest.mark.asyncio
async def test_foreign_connection_never_mints_authorization_plan():
    host, request = host_context(owner=False)
    with pytest.raises(HTTPException) as err:
        await api.revoke_personal_whatsapp_risk(
            connection_id=api.UUID(CONNECTION), provider_id=PROVIDER,
            request=request, user=actor(),
        )
    assert err.value.status_code == 403
    host.activation.issue_action_plan.assert_not_awaited()
    host.revoke_personal_pairing_risk.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"tenant_id": "default"},
    {"user_id": ""},
    {"is_active": False},
    {"is_verified": False},
])
async def test_unverified_actor_fails_before_repository_or_provider(changes):
    host, request = host_context()
    with pytest.raises(HTTPException) as err:
        await api.revoke_personal_whatsapp_risk(
            connection_id=api.UUID(CONNECTION), provider_id=PROVIDER,
            request=request, user=actor(**changes),
        )
    assert err.value.status_code == 403
    host.repository.get_connection.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_risk_acceptance_means_no_write():
    host, request = host_context()
    with pytest.raises(HTTPException) as err:
        await api.acknowledge_personal_whatsapp_risk(
            connection_id=api.UUID(CONNECTION), provider_id=PROVIDER,
            payload=api.RiskAcknowledgement(
                accepted=False, policy_version=api.PERSONAL_WHATSAPP_CONSENT_VERSION,
            ),
            request=request, user=actor(),
        )
    assert err.value.status_code == 422
    host.repository.get_connection.assert_not_awaited()
    host.acknowledge_personal_pairing_risk.assert_not_awaited()


@pytest.mark.asyncio
async def test_consent_status_is_unacknowledged_when_sql_has_no_active_record():
    host, request = host_context()
    result = await api.get_personal_whatsapp_risk_status(
        connection_id=api.UUID(CONNECTION), provider_id=PROVIDER,
        request=request, user=actor(),
    )
    assert result.acknowledged is False
    assert result.paired is False
    assert result.provider_unlinked is False
    host.get_personal_pairing_risk.assert_awaited_once()
    host.activation.issue_action_plan.assert_awaited_once()


@pytest.mark.asyncio
async def test_consent_status_requires_current_scoped_unrevoked_evidence():
    from datetime import datetime, timezone
    from ai_karen_engine.services.channels.personal_pairing_policy import (
        PersonalPairingConsent,
    )

    host, request = host_context()
    valid = PersonalPairingConsent(
        tenant_id=TENANT, user_id=USER, connection_id=CONNECTION,
        provider_id=PROVIDER,
        policy_version=api.PERSONAL_WHATSAPP_CONSENT_VERSION,
        accepted_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
    )
    host.get_personal_pairing_risk.return_value = valid
    response = await api.get_personal_whatsapp_risk_status(
        connection_id=api.UUID(CONNECTION), provider_id=PROVIDER,
        request=request, user=actor(),
    )
    assert response.acknowledged is True
    assert response.paired is False
    host.get_personal_pairing_risk.return_value = PersonalPairingConsent(
        tenant_id=TENANT, user_id=USER, connection_id=CONNECTION,
        provider_id="forged-provider",
        policy_version=api.PERSONAL_WHATSAPP_CONSENT_VERSION,
        accepted_at=valid.accepted_at,
    )
    response = await api.get_personal_whatsapp_risk_status(
        connection_id=api.UUID(CONNECTION), provider_id=PROVIDER,
        request=request, user=actor(),
    )
    assert response.acknowledged is False


@pytest.mark.asyncio
async def test_unowned_connection_cannot_read_consent_record():
    host, request = host_context(owner=False)
    with pytest.raises(HTTPException) as error:
        await api.get_personal_whatsapp_risk_status(
            connection_id=api.UUID(CONNECTION), provider_id=PROVIDER,
            request=request, user=actor(),
        )
    assert error.value.status_code == 403
    host.get_personal_pairing_risk.assert_not_awaited()


@pytest.mark.asyncio
async def test_pairing_status_never_promotes_saved_receipt_to_live_connected():
    host, request = host_context()
    result = await api.get_personal_whatsapp_pairing_status(
        connection_id=api.UUID(CONNECTION), provider_id=PROVIDER,
        request=request, user=actor(),
    )
    assert result.availability == "unavailable"
    assert result.live_connected is False
    assert result.qr_available is False
    host.get_personal_pairing_status.assert_awaited_once()
    kwargs = host.get_personal_pairing_status.await_args.kwargs
    assert kwargs["tenant_id"] == TENANT and kwargs["user_id"] == USER
    assert kwargs["authorized_plan"] == "trusted-plan"


@pytest.mark.asyncio
async def test_foreign_owner_cannot_query_pairing_status():
    host, request = host_context(owner=False)
    with pytest.raises(HTTPException) as exc:
        await api.get_personal_whatsapp_pairing_status(
            connection_id=api.UUID(CONNECTION), provider_id=PROVIDER,
            request=request, user=actor(),
        )
    assert exc.value.status_code == 403
    host.get_personal_pairing_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_operator_assigns_existing_tenant_connection_only_via_fresh_provision_plan():
    host, request = host_context()
    host.assign_personal_connection_owner = AsyncMock(return_value=True)
    operator = actor(roles=["admin"])

    response = await api.assign_personal_channel_owner(
        connection_id=api.UUID(CONNECTION),
        payload=api.PersonalOwnerAssignment(owner_user_id=api.UUID(USER)),
        request=request,
        user=operator,
    )

    assert response.owner_assigned is True
    assert response.paired is False
    assert response.qr_available is False
    assert response.provider_unlinked is False
    host.repository.get_connection.assert_awaited_once_with(
        tenant_id=TENANT, connection_id=CONNECTION,
    )
    host.activation.issue_action_plan.assert_awaited_once()
    grant = host.activation.issue_action_plan.await_args.kwargs
    assert grant["tenant_id"] == TENANT
    assert grant["user_id"] == USER
    assert grant["session_id"]
    assert grant["installation_id"] == "whatsapp-cloud"
    assert grant["action"] == "channel.provision"

    host.assign_personal_connection_owner.assert_awaited_once_with(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        owner_user_id=USER,
        operator_user_id=USER,
        session_id=grant["session_id"],
        authorized_plan="trusted-plan",
    )
    host.acknowledge_personal_pairing_risk.assert_not_awaited()


@pytest.mark.asyncio
async def test_operator_assignment_denied_when_canonical_policy_rejects_fresh_principal():
    host, request = host_context()
    host.activation.issue_action_plan.side_effect = PermissionError(
        "Canonical RBAC denies channel action"
    )
    host.assign_personal_connection_owner = AsyncMock()

    with pytest.raises(HTTPException) as err:
        await api.assign_personal_channel_owner(
            connection_id=api.UUID(CONNECTION),
            payload=api.PersonalOwnerAssignment(owner_user_id=api.UUID(USER)),
            request=request,
            user=actor(roles=["user"]),
        )
    assert err.value.status_code == 403
    assert "RBAC" not in err.value.detail
    host.assign_personal_connection_owner.assert_not_awaited()


@pytest.mark.asyncio
async def test_operator_assignment_fails_without_cross_tenant_connection_scope():
    host, request = host_context()
    host.repository.get_connection.return_value = ChannelConnection(
        connection_id=CONNECTION,
        tenant_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        installation_id="whatsapp-cloud",
        provider_account_id="account",
        credential_handle="vault://ref",
        revision=1,
        enabled=False,
    )
    host.assign_personal_connection_owner = AsyncMock()

    with pytest.raises(HTTPException) as err:
        await api.assign_personal_channel_owner(
            connection_id=api.UUID(CONNECTION),
            payload=api.PersonalOwnerAssignment(owner_user_id=api.UUID(USER)),
            request=request,
            user=actor(roles=["admin"]),
        )
    assert err.value.status_code == 403
    host.activation.issue_action_plan.assert_not_awaited()
    host.assign_personal_connection_owner.assert_not_awaited()


@pytest.mark.asyncio
async def test_operator_assignment_cannot_reassign_owner_or_claim_accepted_session():
    host, request = host_context()
    host.assign_personal_connection_owner = AsyncMock(return_value=False)

    with pytest.raises(HTTPException) as err:
        await api.assign_personal_channel_owner(
            connection_id=api.UUID(CONNECTION),
            payload=api.PersonalOwnerAssignment(owner_user_id=api.UUID(USER)),
            request=request,
            user=actor(roles=["admin"]),
        )
    assert err.value.status_code == 409
    assert err.value.detail == "Connection owner not assigned"
    host.assign_personal_connection_owner.assert_awaited_once()
    host.get_personal_pairing_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_operator_assignment_exposes_no_internal_database_or_provider_failure():
    host, request = host_context()
    host.assign_personal_connection_owner = AsyncMock(
        side_effect=RuntimeError("private vendor session token must stay hidden")
    )

    with pytest.raises(HTTPException) as err:
        await api.assign_personal_channel_owner(
            connection_id=api.UUID(CONNECTION),
            payload=api.PersonalOwnerAssignment(owner_user_id=api.UUID(USER)),
            request=request,
            user=actor(roles=["admin"]),
        )
    assert err.value.status_code == 503
    assert err.value.detail == "Personal channel ownership unavailable"
    assert "private vendor" not in err.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"tenant_id": "default"},
    {"user_id": ""},
    {"is_active": False},
    {"is_verified": False},
])
async def test_operator_assignment_refuses_unverified_session_principal(changes):
    host, request = host_context()
    host.assign_personal_connection_owner = AsyncMock()
    with pytest.raises(HTTPException) as err:
        await api.assign_personal_channel_owner(
            connection_id=api.UUID(CONNECTION),
            payload=api.PersonalOwnerAssignment(owner_user_id=api.UUID(USER)),
            request=request,
            user=actor(roles=["admin"], **changes),
        )
    assert err.value.status_code == 403
    host.repository.get_connection.assert_not_awaited()
    host.activation.issue_action_plan.assert_not_awaited()
    host.assign_personal_connection_owner.assert_not_awaited()


def test_operator_assignment_schema_forbids_actor_tenant_or_provider_claims():
    for forbidden in ("operator_user_id", "tenant_id", "session_id", "provider_id", "authorized_plan"):
        with pytest.raises(ValidationError):
            api.PersonalOwnerAssignment.model_validate({
                "owner_user_id": USER,
                forbidden: "forged",
            })
    with pytest.raises(ValidationError):
        api.PersonalOwnerAssignment.model_validate({"owner_user_id": "not-a-uuid"})


def test_operator_assignment_route_requires_canonical_session_authentication():
    paths = [
        route for route in api.router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/channels/personal/{connection_id}/owner"
    ]
    assert len(paths) == 1
    route = paths[0]
    assert route.methods == {"POST"}
    assert route.status_code == 201
    assert any(
        dependency.call is api.get_current_user
        for dependency in route.dependant.dependencies
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("unapproved", ["missing_provider", "missing_signing_secret"])
async def test_operator_assignment_requires_configured_managed_personal_provider(unapproved):
    host, request = host_context()
    host.assign_personal_connection_owner = AsyncMock()
    if unapproved == "missing_provider":
        host.settings.personal_pairing_providers = {}
    else:
        host.settings.installations = {"whatsapp-cloud": frozenset({"access_token"})}
    with pytest.raises(HTTPException) as err:
        await api.assign_personal_channel_owner(
            connection_id=api.UUID(CONNECTION),
            payload=api.PersonalOwnerAssignment(owner_user_id=api.UUID(USER)),
            request=request,
            user=actor(roles=["admin"]),
        )
    assert err.value.status_code == 403
    host.activation.issue_action_plan.assert_not_awaited()
    host.assign_personal_connection_owner.assert_not_awaited()

