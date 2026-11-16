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
from ai_karen_engine.services.channels.consent_recovery import (
    assess_retirement_evidence_snapshot,
)

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
    host.list_owned_personal_channels = AsyncMock(return_value=[])
    host.get_personal_pairing_risk = AsyncMock(return_value=None)
    host.get_personal_pairing_status = AsyncMock(return_value={
        "availability": "unavailable", "last_observed_phase": None,
        "live_connected": False, "qr_available": False,
        "provider_unlinked": False,
    })
    host.place_personal_retirement_hold = AsyncMock(return_value={
        "hold_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "connection_revision": 2, "hold_recorded": True,
        "connection_enabled": False, "created_new": True,
        "local_stop_attempted": True, "local_stop_succeeded": False,
        "provider_unlinked": False, "credentials_erased": False,
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
    assert result.has_active_consent is False
    assert result.paired is False
    assert result.provider_unlinked is False
    host.get_personal_pairing_risk.assert_awaited_once()
    host.activation.issue_action_plan.assert_awaited_once()


@pytest.mark.asyncio
async def test_consent_read_serves_canonical_versioned_disclosure_without_claiming_pairing():
    from ai_karen_engine.services.channels.personal_pairing_policy import (
        PERSONAL_WHATSAPP_RISK_NOTICE_TEXT,
        PERSONAL_WHATSAPP_RISK_NOTICE_TITLE,
    )

    host, request = host_context()
    result = await api.get_personal_whatsapp_risk_status(
        connection_id=api.UUID(CONNECTION), provider_id=PROVIDER,
        request=request, user=actor(),
    )
    assert result.policy_version == api.PERSONAL_WHATSAPP_CONSENT_VERSION
    assert result.notice_title == PERSONAL_WHATSAPP_RISK_NOTICE_TITLE
    assert result.notice_text == PERSONAL_WHATSAPP_RISK_NOTICE_TEXT
    assert "not supported or endorsed by WhatsApp/Meta" in result.notice_text
    assert "permanently banned" in result.notice_text
    assert "third-party operator" in result.notice_text
    assert "Disconnect does not guarantee deletion" in result.notice_text
    assert not result.acknowledged
    assert not result.paired
    assert not result.provider_unlinked
    assert not hasattr(result, "credential_handle")
    host.acknowledge_personal_pairing_risk.assert_not_awaited()


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
    assert response.has_active_consent is True
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
    assert response.has_active_consent is False


@pytest.mark.asyncio
async def test_active_old_version_consent_is_not_current_but_remains_revocable():
    from datetime import datetime, timezone
    from ai_karen_engine.services.channels.personal_pairing_policy import (
        PersonalPairingConsent,
    )
    host, request = host_context()
    host.get_personal_pairing_risk.return_value = PersonalPairingConsent(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        user_id=USER,
        provider_id=PROVIDER,
        policy_version="whatsapp-personal-risk-obsolete",
        accepted_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
    )
    status = await api.get_personal_whatsapp_risk_status(
        connection_id=api.UUID(CONNECTION), provider_id=PROVIDER,
        request=request, user=actor(),
    )
    assert status.acknowledged is False
    assert status.has_active_consent is True
    assert status.paired is False
    assert status.provider_unlinked is False
    revoked = await api.revoke_personal_whatsapp_risk(
        connection_id=api.UUID(CONNECTION), provider_id=PROVIDER,
        request=request, user=actor(),
    )
    assert revoked.revoked is True
    assert revoked.provider_unlinked is False
    host.revoke_personal_pairing_risk.assert_awaited_once()


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
@pytest.mark.parametrize("forged", [
    {"live_connected": True},
    {"live_connected": 1},
    {"qr_available": True},
    {"qr_available": 0},
    {"availability": "available"},
    {"last_observed_phase": "remotely_verified"},
    {"provider_unlinked": True},
    {"provider_unlinked": "true"},
    {"session_reference": "vendor-private-session"},
])
async def test_pairing_status_rejects_unsupported_live_or_malformed_host_claims(forged):
    host, request = host_context()
    host.get_personal_pairing_status.return_value = {
        "availability": "unavailable",
        "last_observed_phase": "connected",
        "live_connected": False,
        "qr_available": False,
        "provider_unlinked": False,
        **forged,
    }
    with pytest.raises(HTTPException) as error:
        await api.get_personal_whatsapp_pairing_status(
            connection_id=api.UUID(CONNECTION), provider_id=PROVIDER,
            request=request, user=actor(),
        )
    assert error.value.status_code == 503
    assert error.value.detail == "Personal channel status unavailable"
    assert "vendor-private-session" not in error.value.detail
    host.get_personal_pairing_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_pairing_status_keeps_vendor_unlink_claim_without_asserting_live_erasure():
    host, request = host_context()
    host.get_personal_pairing_status.return_value = {
        "availability": "configured",
        "last_observed_phase": "disconnected",
        "live_connected": False,
        "qr_available": False,
        "provider_unlinked": True,
    }
    result = await api.get_personal_whatsapp_pairing_status(
        connection_id=api.UUID(CONNECTION), provider_id=PROVIDER,
        request=request, user=actor(),
    )
    assert result.provider_unlinked is True
    assert result.live_connected is False
    assert result.qr_available is False


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



@pytest.mark.asyncio
async def test_owner_inventory_uses_authenticated_principal_only():
    host, request = host_context()
    host.list_owned_personal_channels.return_value = [{
        "connection_id": CONNECTION,
        "installation_id": "whatsapp-cloud",
        "provider_id": PROVIDER,
        "active_consent_provider_ids": ["disabled-provider"],
        "availability": "unavailable",
        "last_observed_phase": "connected",
        "live_connected": False,
        "qr_available": False,
        "provider_unlinked": False,
    }]
    result = await api.list_personal_channel_connections(
        request=request, user=actor(),
    )
    host.list_owned_personal_channels.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER,
    )
    assert len(result.connections) == 1
    channel = result.connections[0]
    assert channel.connection_id == CONNECTION
    assert channel.active_consent_provider_ids == ["disabled-provider"]
    assert channel.last_observed_phase == "connected"
    assert channel.live_connected is False
    assert channel.qr_available is False
    assert "credential_handle" not in channel.model_dump()
    assert "provider_account_id" not in channel.model_dump()



@pytest.mark.asyncio
@pytest.mark.parametrize("forged", [
    {"live_connected": True},
    {"live_connected": "true"},
    {"qr_available": True},
    {"qr_available": 0},
    {"availability": "operational"},
    {"last_observed_phase": "verified_connected"},
    {"provider_unlinked": True},
    {"provider_unlinked": 1},
    {"provider_receipt_id": "private-vendor-receipt"},
])
async def test_owner_inventory_denies_forged_live_status_without_exposing_secrets(forged):
    host, request = host_context()
    host.list_owned_personal_channels.return_value = [{
        "connection_id": CONNECTION,
        "installation_id": "whatsapp-cloud",
        "provider_id": PROVIDER,
        "active_consent_provider_ids": [],
        "availability": "unavailable",
        "last_observed_phase": "connected",
        "live_connected": False,
        "qr_available": False,
        "provider_unlinked": False,
        **forged,
    }]
    with pytest.raises(HTTPException) as error:
        await api.list_personal_channel_connections(
            request=request, user=actor(),
        )
    assert error.value.status_code == 503
    assert error.value.detail == "Personal channel status unavailable"
    assert "private-vendor-receipt" not in error.value.detail
    host.list_owned_personal_channels.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER,
    )


@pytest.mark.asyncio
async def test_owner_inventory_handles_empty_backend_without_synthetic_connections():
    host, request = host_context()
    result = await api.list_personal_channel_connections(
        request=request, user=actor(),
    )
    assert result.connections == []
    host.list_owned_personal_channels.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"tenant_id": "default"},
    {"user_id": ""},
    {"is_active": False},
    {"is_verified": False},
])
async def test_owner_inventory_refuses_invalid_session_principal(changes):
    host, request = host_context()
    with pytest.raises(HTTPException) as exc:
        await api.list_personal_channel_connections(
            request=request, user=actor(**changes),
        )
    assert exc.value.status_code == 403
    host.list_owned_personal_channels.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_inventory_rejects_host_policy_denial_and_hides_internal_exception():
    host, request = host_context()
    host.list_owned_personal_channels.side_effect = PermissionError("denied")
    with pytest.raises(HTTPException) as exc:
        await api.list_personal_channel_connections(
            request=request, user=actor(),
        )
    assert exc.value.status_code == 403
    host.list_owned_personal_channels.side_effect = RuntimeError(
        "vault://private-ref"
    )
    with pytest.raises(HTTPException) as unavailable:
        await api.list_personal_channel_connections(
            request=request, user=actor(),
        )
    assert unavailable.value.status_code == 503
    assert "vault://" not in unavailable.value.detail


def test_owner_inventory_api_is_authenticated_and_get_only():
    routes = [
        route for route in api.router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/channels/personal/connections"
    ]
    assert len(routes) == 1
    assert routes[0].methods == {"GET"}
    assert any(
        dependency.call is api.get_current_user
        for dependency in routes[0].dependant.dependencies
    )


def retired_recovery_context(monkeypatch, *, consents=None, revoked=True):
    """A real request can use recovery even when no ChannelHost exists."""
    recovery = SimpleNamespace(
        list_active=AsyncMock(return_value=consents if consents is not None else [{
            "connection_id": CONNECTION,
            "provider_id": PROVIDER,
            "policy_version": "obsolete-policy",
        }]),
        revoke=AsyncMock(return_value=revoked),
        list_retirement_evidence=AsyncMock(return_value=[
            assess_retirement_evidence_snapshot({
                "connection_id": CONNECTION, "connection_revision": 2,
                "connection_enabled": False, "retirement_held": False,
                "active_consent": False,
                "unresolved_pairing": True,
                "provider_unlink_claim_recorded": False,
                "deletion_request_recorded": True,
                "credential_deletion_claim_recorded": False,
                "provider_revision_claims_correlated": False,
                "unverified_deletion_request": True,
                "inbox_not_completed": False,
                "outbound_not_confirmed": True,
            }),
        ]),
        list_deletion_requests=AsyncMock(return_value=[{
            "request_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
            "connection_id": CONNECTION, "provider_id": PROVIDER,
            "connection_revision": 2, "status": "provider_claimed",
        }]),
    )
    monkeypatch.setattr(api, "PersonalConsentRecoveryService", lambda: recovery)
    return recovery


@pytest.mark.asyncio
async def test_retired_consent_inventory_needs_only_current_auth_not_channel_host(monkeypatch):
    recovery = retired_recovery_context(monkeypatch)
    result = await api.list_personal_consent_recovery(user=actor())
    assert len(result.consents) == 1
    assert result.consents[0].provider_id == PROVIDER
    assert result.consents[0].policy_version == "obsolete-policy"
    recovery.list_active.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER,
    )
    assert "credential_handle" not in result.consents[0].model_dump()
    assert "provider_account_id" not in result.consents[0].model_dump()


@pytest.mark.asyncio
async def test_retired_consent_revoke_receipt_never_claims_unlink_or_pairing(monkeypatch):
    recovery = retired_recovery_context(monkeypatch)
    receipt = await api.revoke_retired_personal_consent(
        connection_id=api.UUID(CONNECTION),
        provider_id=PROVIDER,
        user=actor(),
    )
    recovery.revoke.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER,
        connection_id=CONNECTION, provider_id=PROVIDER,
    )
    assert receipt.revoked is True
    assert receipt.paired is False
    assert receipt.provider_unlinked is False
    recovery.revoke.return_value = False
    receipt = await api.revoke_retired_personal_consent(
        connection_id=api.UUID(CONNECTION),
        provider_id=PROVIDER,
        user=actor(),
    )
    assert receipt.revoked is False


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"user_id": "forged"},
    {"tenant_id": "default"},
    {"is_active": False},
    {"is_verified": False},
])
async def test_retired_consent_recovery_rejects_inactive_or_unverified_actor(monkeypatch, changes):
    recovery = retired_recovery_context(monkeypatch)
    with pytest.raises(HTTPException) as e:
        await api.list_personal_consent_recovery(user=actor(**changes))
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        await api.revoke_retired_personal_consent(
            connection_id=api.UUID(CONNECTION), provider_id=PROVIDER,
            user=actor(**changes),
        )
    assert e.value.status_code == 403
    recovery.list_active.assert_not_awaited()
    recovery.revoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_retired_consent_recovery_denials_and_errors_are_redacted(monkeypatch):
    recovery = retired_recovery_context(monkeypatch)
    recovery.list_active.side_effect = PermissionError("other tenant owner")
    with pytest.raises(HTTPException) as e:
        await api.list_personal_consent_recovery(user=actor())
    assert e.value.status_code == 403
    assert "other tenant" not in e.value.detail
    recovery.revoke.side_effect = RuntimeError("vault://sensitive-token")
    with pytest.raises(HTTPException) as e:
        await api.revoke_retired_personal_consent(
            connection_id=api.UUID(CONNECTION), provider_id=PROVIDER,
            user=actor(),
        )
    assert e.value.status_code == 503
    assert "vault://" not in e.value.detail


@pytest.mark.asyncio
async def test_retired_recovery_refuses_invalid_provider_before_service(monkeypatch):
    recovery = retired_recovery_context(monkeypatch)
    for provider_id in ("", "  ", "x" * 129):
        with pytest.raises(HTTPException) as e:
            await api.revoke_retired_personal_consent(
                connection_id=api.UUID(CONNECTION),
                provider_id=provider_id,
                user=actor(),
            )
        assert e.value.status_code == 422
    recovery.revoke.assert_not_awaited()


def test_retired_consent_recovery_routes_are_authenticated_and_not_activation_routes():
    routes = [route for route in api.router.routes if isinstance(route, APIRoute)]
    for path, method in (
        ("/api/channels/personal/consent-recovery", "GET"),
        ("/api/channels/personal/consent-recovery/deletion-requests", "GET"),
        ("/api/channels/personal/consent-recovery/retirement-evidence", "GET"),
        ("/api/channels/personal/consent-recovery/{connection_id}/{provider_id}/revoke", "POST"),
    ):
        matches = [route for route in routes if route.path == path]
        assert len(matches) == 1
        assert matches[0].methods == {method}
        assert any(
            dep.call is api.get_current_user
            for dep in matches[0].dependant.dependencies
        )



@pytest.mark.asyncio
async def test_retired_deletion_requests_are_auth_only_and_never_claim_verified_erasure(monkeypatch):
    recovery = retired_recovery_context(monkeypatch)
    result = await api.list_retired_credential_deletion_requests(user=actor())
    assert len(result.requests) == 1
    record = result.requests[0].model_dump()
    assert record["status"] == "provider_claimed"
    assert record["connection_revision"] == 2
    for field in ("session_reference", "credential_scope", "provider_receipt_id",
                  "credential_handle", "provider_unlinked", "credentials_erased"):
        assert field not in record
    recovery.list_deletion_requests.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER,
    )


@pytest.mark.asyncio
async def test_retired_deletion_requests_denied_and_errors_redacted(monkeypatch):
    recovery = retired_recovery_context(monkeypatch)
    with pytest.raises(HTTPException) as forbidden:
        await api.list_retired_credential_deletion_requests(
            user=actor(is_verified=False),
        )
    assert forbidden.value.status_code == 403
    recovery.list_deletion_requests.assert_not_awaited()
    recovery.list_deletion_requests.side_effect = RuntimeError("vault://secret-token")
    with pytest.raises(HTTPException) as unavailable:
        await api.list_retired_credential_deletion_requests(user=actor())
    assert unavailable.value.status_code == 503
    assert "vault://" not in unavailable.value.detail


@pytest.mark.asyncio
async def test_retirement_evidence_api_requires_identity_and_never_claims_deletion(monkeypatch):
    recovery = retired_recovery_context(monkeypatch)
    result = await api.list_retired_channel_evidence(user=actor())
    item = result.connections[0].model_dump()
    assert item["unresolved_pairing"] is True
    assert item["provider_unlink_claim_recorded"] is False
    assert item["credential_deletion_claim_recorded"] is False
    assert item["provider_revision_claims_correlated"] is False
    assert item["retirement_assessment"]["contract_version"] == "retirement-verification-readiness-v2"
    assert item["outbound_not_confirmed"] is True
    assessment = item["retirement_assessment"]
    assert assessment["contract_version"] == "retirement-verification-readiness-v2"
    assert assessment["status"] == "blocked"
    assert assessment["cleanup_authorized"] is False
    assert assessment["provider_unlink_independently_verified"] is False
    assert "governed_final_cleanup_authority_unavailable" in assessment["blocking_reasons"]
    for secret in ("credential_handle", "session_reference", "provider_receipt_id",
                   "message_text", "retirement_authorized", "provider_unlinked"):
        assert secret not in item
    recovery.list_retirement_evidence.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER,
    )
    with pytest.raises(HTTPException) as forbidden:
        await api.list_retired_channel_evidence(user=actor(is_verified=False))
    assert forbidden.value.status_code == 403
    recovery.list_retirement_evidence.side_effect = RuntimeError("vault://private")
    with pytest.raises(HTTPException) as unavailable:
        await api.list_retired_channel_evidence(user=actor())
    assert unavailable.value.status_code == 503
    assert "vault://" not in unavailable.value.detail


@pytest.mark.asyncio
async def test_operator_retirement_hold_is_explicit_scoped_and_never_provider_erasure():
    host, request = host_context()
    payload = api.PersonalRetirementHoldRequest(
        expected_revision=1,
        idempotency_key=api.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
    )
    response = await api.place_personal_retirement_hold(
        connection_id=api.UUID(CONNECTION), payload=payload,
        request=request, user=actor(roles=["admin"]),
    )
    assert response.hold_recorded is True
    assert response.connection_enabled is False
    assert response.connection_revision == 2
    assert response.local_stop_attempted is True
    assert response.local_stop_succeeded is False
    assert response.provider_unlinked is False
    assert response.credentials_erased is False
    grant = host.activation.issue_action_plan.await_args.kwargs
    assert grant["action"] == "channel.deactivate"
    assert grant["tenant_id"] == TENANT and grant["user_id"] == USER
    host.place_personal_retirement_hold.assert_awaited_once_with(
        tenant_id=TENANT, connection_id=CONNECTION,
        operator_user_id=USER, session_id=grant["session_id"],
        authorized_plan="trusted-plan", expected_revision=1,
        idempotency_key="ffffffff-ffff-ffff-ffff-ffffffffffff",
    )
    for secret in ("credential_handle", "session_reference", "provider_account_id",
                   "retirement_authorized", "vendor_erasure_verified"):
        assert secret not in response.model_dump()


@pytest.mark.asyncio
async def test_retirement_hold_canonical_policy_denial_never_reaches_repository():
    host, request = host_context()
    host.activation.issue_action_plan.side_effect = PermissionError("private RBAC")
    with pytest.raises(HTTPException) as err:
        await api.place_personal_retirement_hold(
            connection_id=api.UUID(CONNECTION),
            payload=api.PersonalRetirementHoldRequest(
                expected_revision=1,
                idempotency_key=api.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
            ),
            request=request, user=actor(roles=["user"]),
        )
    assert err.value.status_code == 403
    assert "RBAC" not in err.value.detail
    host.place_personal_retirement_hold.assert_not_awaited()


@pytest.mark.asyncio
async def test_retirement_hold_rejects_cross_tenant_or_invalid_principal():
    host, request = host_context()
    payload = api.PersonalRetirementHoldRequest(
        expected_revision=1,
        idempotency_key=api.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
    )
    host.repository.get_connection.return_value = ChannelConnection(
        connection_id=CONNECTION, tenant_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        installation_id="whatsapp-cloud",
        provider_account_id="private", credential_handle="vault://private",
        revision=1, enabled=True,
    )
    with pytest.raises(HTTPException) as err:
        await api.place_personal_retirement_hold(
            connection_id=api.UUID(CONNECTION), payload=payload,
            request=request, user=actor(roles=["admin"]),
        )
    assert err.value.status_code == 403
    host.activation.issue_action_plan.assert_not_awaited()
    host.place_personal_retirement_hold.assert_not_awaited()
    with pytest.raises(HTTPException) as err:
        await api.place_personal_retirement_hold(
            connection_id=api.UUID(CONNECTION), payload=payload,
            request=request, user=actor(is_verified=False),
        )
    assert err.value.status_code == 403


@pytest.mark.asyncio
async def test_retirement_hold_revision_conflict_and_error_redaction():
    from ai_karen_engine.persistence.repositories.channel_repository import (
        ChannelRetirementConflict,
    )
    host, request = host_context()
    payload = api.PersonalRetirementHoldRequest(
        expected_revision=1,
        idempotency_key=api.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
    )
    host.place_personal_retirement_hold.side_effect = ChannelRetirementConflict(
        "private stale revision",
    )
    with pytest.raises(HTTPException) as err:
        await api.place_personal_retirement_hold(
            connection_id=api.UUID(CONNECTION), payload=payload,
            request=request, user=actor(roles=["admin"]),
        )
    assert err.value.status_code == 409
    assert "private" not in err.value.detail
    host.place_personal_retirement_hold.side_effect = RuntimeError("vault://private")
    with pytest.raises(HTTPException) as err:
        await api.place_personal_retirement_hold(
            connection_id=api.UUID(CONNECTION), payload=payload,
            request=request, user=actor(roles=["admin"]),
        )
    assert err.value.status_code == 503
    assert "vault://" not in err.value.detail


def test_retirement_hold_api_contract_is_authenticated_and_strict():
    routes = [
        route for route in api.router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/channels/personal/{connection_id}/retirement-hold"
    ]
    assert len(routes) == 1
    assert routes[0].methods == {"POST"}
    assert any(
        dependency.call is api.get_current_user
        for dependency in routes[0].dependant.dependencies
    )
    with pytest.raises(ValidationError):
        api.PersonalRetirementHoldRequest(
            expected_revision=True,
            idempotency_key="ffffffff-ffff-ffff-ffff-ffffffffffff",
        )
    with pytest.raises(ValidationError):
        api.PersonalRetirementHoldRequest(
            expected_revision=1,
            idempotency_key="ffffffff-ffff-ffff-ffff-ffffffffffff",
            operator_user_id=USER,
        )


@pytest.mark.asyncio
async def test_retirement_api_refuses_fake_cleanup_grant_and_redacts_invalid_evidence(monkeypatch):
    recovery = retired_recovery_context(monkeypatch)
    original = recovery.list_retirement_evidence.return_value[0]
    corrupted = {
        **original,
        "retirement_assessment": {
            **original["retirement_assessment"],
            "cleanup_authorized": True,
        },
    }
    recovery.list_retirement_evidence.return_value = [corrupted]
    with pytest.raises(HTTPException) as err:
        await api.list_retired_channel_evidence(user=actor())
    assert err.value.status_code == 503
    assert "cleanup_authorized" not in err.value.detail

    # Even a forged historical 'verified' ledger label cannot remove the
    # mandatory independently verified-erasure blockers from this response.
    bad = {
        **original,
        "retirement_assessment": {
            **original["retirement_assessment"],
            # Four valid local reason codes alone are not sufficient; all
            # independent verification prerequisites remain mandatory.
            "blocking_reasons": [
                "local_retirement_hold_missing",
                "active_pairing_consent_remains",
                "pairing_teardown_unresolved",
                "credential_deletion_request_missing",
            ],
        },
    }
    recovery.list_retirement_evidence.return_value = [bad]
    with pytest.raises(HTTPException) as err:
        await api.list_retired_channel_evidence(user=actor())
    assert err.value.status_code == 503


def test_retirement_review_response_schema_never_accepts_destructive_capability():
    valid = assess_retirement_evidence_snapshot({
        "connection_id": CONNECTION, "connection_revision": 2,
        "connection_enabled": False, "retirement_held": True,
        "active_consent": False, "unresolved_pairing": False,
        "provider_unlink_claim_recorded": True,
        "deletion_request_recorded": True,
        "credential_deletion_claim_recorded": True,
        "provider_revision_claims_correlated": True,
        "unverified_deletion_request": True,
        "inbox_not_completed": False, "outbound_not_confirmed": False,
    })
    assert api.PersonalRetirementEvidenceItem(**valid).retirement_assessment.cleanup_authorized is False
    for forge in (
        {"cleanup_authorized": True},
        {"status": "verified"},
        {"provider_unlink_independently_verified": True},
        {"credential_erasure_independently_verified": True},
        {"retention_scope_verified": True},
        {"contract_version": "retirement-verification-readiness-v3"},
    ):
        with pytest.raises(ValidationError):
            api.PersonalRetirementEvidenceItem(**{
                **valid,
                "retirement_assessment": {
                    **valid["retirement_assessment"],
                    **forge,
                },
            })


def test_retirement_api_rejects_unsupported_correlated_claim_downgrade():
    complete = assess_retirement_evidence_snapshot({
        "connection_id": CONNECTION, "connection_revision": 2,
        "connection_enabled": False, "retirement_held": True,
        "active_consent": False, "unresolved_pairing": False,
        "provider_unlink_claim_recorded": True,
        "deletion_request_recorded": True,
        "credential_deletion_claim_recorded": True,
        "provider_revision_claims_correlated": False,
        "unverified_deletion_request": True,
        "inbox_not_completed": False, "outbound_not_confirmed": False,
    })
    blockers = complete["retirement_assessment"]["blocking_reasons"]
    assert "provider_revision_claims_mismatched" in blockers
    with pytest.raises(ValidationError):
        api.PersonalRetirementEvidenceItem(**{
            **complete, "retirement_assessment": {
                **complete["retirement_assessment"],
                "blocking_reasons": [
                    reason for reason in blockers
                    if reason != "provider_unlink_independent_verification_unavailable"
                ],
            },
        })


def test_retirement_response_validator_rejects_fake_correlation_or_missing_mismatch():
    from ai_karen_engine.services.channels.consent_recovery import (
        assess_retirement_evidence_snapshot,
    )
    raw = {
        "connection_id": CONNECTION, "connection_revision": 8,
        "connection_enabled": False, "retirement_held": True,
        "active_consent": False, "unresolved_pairing": False,
        "provider_unlink_claim_recorded": True,
        "deletion_request_recorded": True,
        "credential_deletion_claim_recorded": True,
        "provider_revision_claims_correlated": False,
        "unverified_deletion_request": True,
        "inbox_not_completed": False, "outbound_not_confirmed": True,
    }
    mismatched = assess_retirement_evidence_snapshot(raw)
    assert api.PersonalRetirementEvidenceItem(**mismatched).retirement_assessment.cleanup_authorized is False
    for malicious in (
        {
            **mismatched,
            "retirement_assessment": {
                **mismatched["retirement_assessment"],
                "blocking_reasons": [
                    code for code in mismatched["retirement_assessment"]["blocking_reasons"]
                    if code != "provider_revision_claims_mismatched"
                ],
            },
        },
        {**mismatched, "provider_revision_claims_correlated": True},
        {
            **mismatched,
            "provider_revision_claims_correlated": True,
            "credential_deletion_claim_recorded": False,
        },
    ):
        with pytest.raises(ValidationError):
            api.PersonalRetirementEvidenceItem(**malicious)

    legitimate = assess_retirement_evidence_snapshot({
        **raw, "provider_revision_claims_correlated": True,
    })
    assert api.PersonalRetirementEvidenceItem(**legitimate).provider_revision_claims_correlated is True


@pytest.mark.parametrize("changed_fact", [
    {"inbox_not_completed": True},
    {"outbound_not_confirmed": True},
    {"unresolved_pairing": True},
    {"active_consent": True},
    {"connection_enabled": True},
    {"retirement_held": False},
    {"deletion_request_recorded": False},
    {"unverified_deletion_request": False},
    {"provider_unlink_claim_recorded": False},
    {"credential_deletion_claim_recorded": False},
    {"provider_revision_claims_correlated": False},
])
def test_retirement_response_rejects_local_evidence_blocker_contradictions(changed_fact):
    raw = {
        "connection_id": CONNECTION, "connection_revision": 4,
        "connection_enabled": False, "retirement_held": True,
        "active_consent": False, "unresolved_pairing": False,
        "provider_unlink_claim_recorded": True,
        "deletion_request_recorded": True,
        "credential_deletion_claim_recorded": True,
        "provider_revision_claims_correlated": True,
        "unverified_deletion_request": True,
        "inbox_not_completed": False,
        "outbound_not_confirmed": False,
    }
    complete = assess_retirement_evidence_snapshot(raw)
    assert api.PersonalRetirementEvidenceItem(**complete)
    with pytest.raises(ValidationError):
        api.PersonalRetirementEvidenceItem(**{**complete, **changed_fact})


@pytest.mark.parametrize("changed", [
    {"connection_revision": "4"},
    {"connection_revision": True},
    {"connection_id": " "},
    {"inbox_not_completed": 1},
    {"outbound_not_confirmed": "false"},
    {"retirement_held": 1},
])
def test_retirement_response_disallows_pydantic_type_coercion(changed):
    good = assess_retirement_evidence_snapshot({
        "connection_id": CONNECTION, "connection_revision": 4,
        "connection_enabled": False, "retirement_held": True,
        "active_consent": False, "unresolved_pairing": False,
        "provider_unlink_claim_recorded": True,
        "deletion_request_recorded": True,
        "credential_deletion_claim_recorded": True,
        "provider_revision_claims_correlated": True,
        "unverified_deletion_request": True,
        "inbox_not_completed": False,
        "outbound_not_confirmed": False,
    })
    with pytest.raises(ValidationError):
        api.PersonalRetirementEvidenceItem(**{**good, **changed})


def test_retirement_response_rejects_extra_stale_or_reordered_known_blockers():
    good = assess_retirement_evidence_snapshot({
        "connection_id": CONNECTION, "connection_revision": 4,
        "connection_enabled": False, "retirement_held": True,
        "active_consent": False, "unresolved_pairing": False,
        "provider_unlink_claim_recorded": True,
        "deletion_request_recorded": True,
        "credential_deletion_claim_recorded": True,
        "provider_revision_claims_correlated": True,
        "unverified_deletion_request": True,
        "inbox_not_completed": False,
        "outbound_not_confirmed": False,
    })
    reasons = good["retirement_assessment"]["blocking_reasons"]
    cases = [
        ["pairing_teardown_unresolved", *reasons],
        list(reversed(reasons)),
    ]
    for codes in cases:
        with pytest.raises(ValidationError):
            api.PersonalRetirementEvidenceItem(**{
                **good,
                "retirement_assessment": {
                    **good["retirement_assessment"],
                    "blocking_reasons": codes,
                },
            })


@pytest.mark.asyncio
async def test_retirement_endpoint_redacts_contradictory_stored_blockers(monkeypatch):
    recovery = retired_recovery_context(monkeypatch)
    good = recovery.list_retirement_evidence.return_value[0]
    recovery.list_retirement_evidence.return_value = [{
        **good, "outbound_not_confirmed": False,
    }]
    with pytest.raises(HTTPException) as error:
        await api.list_retired_channel_evidence(user=actor())
    assert error.value.status_code == 503
    assert error.value.detail == "Personal channel retirement evidence unavailable"


def test_retirement_api_rejects_forged_historical_verified_status_clearance():
    valid = assess_retirement_evidence_snapshot({
        "connection_id": CONNECTION, "connection_revision": 5,
        "connection_enabled": False, "retirement_held": True,
        "active_consent": False, "unresolved_pairing": False,
        "provider_unlink_claim_recorded": True,
        "deletion_request_recorded": True,
        "credential_deletion_claim_recorded": True,
        "provider_revision_claims_correlated": True,
        "unverified_deletion_request": True,
        "inbox_not_completed": False, "outbound_not_confirmed": False,
    })
    assert "credential_deletion_requests_unverified" in valid["retirement_assessment"]["blocking_reasons"]
    for changed in (
        {"unverified_deletion_request": False},
        {"retirement_assessment": {
            **valid["retirement_assessment"],
            "blocking_reasons": [
                reason for reason in valid["retirement_assessment"]["blocking_reasons"]
                if reason != "credential_deletion_requests_unverified"
            ],
        }},
    ):
        with pytest.raises(ValidationError):
            api.PersonalRetirementEvidenceItem(**{**valid, **changed})


@pytest.mark.asyncio
async def test_telegram_inspection_issues_separate_operator_plan_without_client_identity():
    host, request = host_context()
    host.repository.get_enabled_connection = AsyncMock(return_value=ChannelConnection(
        connection_id=CONNECTION, tenant_id=TENANT,
        installation_id="telegram-bot", provider_account_id="telegram-account",
        credential_handle="vault://telegram", revision=4, enabled=True,
    ))
    host.inspect_channel_webhook = AsyncMock(return_value={
        "registered": True, "path_matches": True,
        "pending_update_count": 2, "provider_reported_error": False,
        "endpoint_origin_verified": False,
    })
    result = await api.inspect_telegram_webhook(
        connection_id=api.UUID(CONNECTION), request=request,
        user=actor(roles=["admin"]),
    )
    assert result.registered is True
    assert result.endpoint_origin_verified is False
    assert host.activation.issue_action_plan.await_args.kwargs["action"] == "channel.inspect"
    assert host.activation.issue_action_plan.await_args.kwargs["tenant_id"] == TENANT
    assert host.activation.issue_action_plan.await_args.kwargs["user_id"] == USER
    assert host.inspect_channel_webhook.await_args.kwargs["authorized_plan"] == "trusted-plan"
    assert host.inspect_channel_webhook.await_args.kwargs["session_id"] == (
        host.activation.issue_action_plan.await_args.kwargs["session_id"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("installation", ["whatsapp-cloud", "telegram-other"])
async def test_telegram_inspection_refuses_other_installations_before_policy(installation):
    host, request = host_context()
    host.repository.get_enabled_connection = AsyncMock(return_value=ChannelConnection(
        connection_id=CONNECTION, tenant_id=TENANT,
        installation_id=installation, provider_account_id="provider",
        credential_handle="vault://ref", revision=2, enabled=True,
    ))
    host.inspect_channel_webhook = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await api.inspect_telegram_webhook(
            connection_id=api.UUID(CONNECTION), request=request, user=actor(roles=["admin"]),
        )
    assert error.value.status_code == 403
    host.activation.issue_action_plan.assert_not_awaited()
    host.inspect_channel_webhook.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_inspection_never_mints_plan_for_absent_connection():
    host, request = host_context()
    host.repository.get_enabled_connection = AsyncMock(return_value=None)
    host.inspect_channel_webhook = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await api.inspect_telegram_webhook(
            connection_id=api.UUID(CONNECTION), request=request, user=actor(roles=["admin"]),
        )
    assert error.value.status_code == 403
    host.activation.issue_action_plan.assert_not_awaited()
    host.inspect_channel_webhook.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_inspection_policy_denial_does_not_read_provider():
    host, request = host_context()
    host.repository.get_enabled_connection = AsyncMock(return_value=ChannelConnection(
        connection_id=CONNECTION, tenant_id=TENANT,
        installation_id="telegram-bot", provider_account_id="provider",
        credential_handle="vault://ref", revision=1, enabled=True,
    ))
    host.activation.issue_action_plan.side_effect = PermissionError("RBAC denied")
    host.inspect_channel_webhook = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await api.inspect_telegram_webhook(
            connection_id=api.UUID(CONNECTION), request=request, user=actor(),
        )
    assert error.value.status_code == 403
    host.inspect_channel_webhook.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_inspection_rejects_invented_live_origin_and_secrets():
    host, request = host_context()
    host.repository.get_enabled_connection = AsyncMock(return_value=ChannelConnection(
        connection_id=CONNECTION, tenant_id=TENANT,
        installation_id="telegram-bot", provider_account_id="provider",
        credential_handle="vault://ref", revision=1, enabled=True,
    ))
    host.inspect_channel_webhook = AsyncMock(return_value={
        "registered": True, "path_matches": True,
        "pending_update_count": 1, "provider_reported_error": False,
        "endpoint_origin_verified": True, "bot_token": "secret",
    })
    with pytest.raises(HTTPException) as error:
        await api.inspect_telegram_webhook(
            connection_id=api.UUID(CONNECTION), request=request, user=actor(roles=["admin"]),
        )
    assert error.value.status_code == 503
    assert "secret" not in str(error.value.detail)


@pytest.mark.asyncio
async def test_telegram_operator_provision_calls_governed_service_and_never_leaks_vault_reference():
    host, request = host_context()
    host.activation.provision = AsyncMock(return_value=ChannelConnection(
        connection_id=CONNECTION, tenant_id=TENANT,
        installation_id="telegram-bot", provider_account_id="telegram-account",
        credential_handle="vault://11111111-1111-1111-1111-111111111111", revision=1, enabled=False,
    ))
    payload = api.TelegramProvisionRequest(
        provider_account_id="telegram-account",
        credential_handle="vault://11111111-1111-1111-1111-111111111111",
    )
    result = await api.provision_telegram_connection(
        payload=payload, request=request, user=actor(roles=["admin"]),
    )
    assert str(result.connection_id) == CONNECTION
    assert result.enabled is False
    assert result.operational is False
    assert "vault://" not in result.model_dump_json()
    assert "telegram-account" not in result.model_dump_json()
    auth = host.activation.issue_action_plan.await_args.kwargs
    assert auth["action"] == "channel.provision"
    assert auth["installation_id"] == "telegram-bot"
    assert auth["tenant_id"] == TENANT and auth["user_id"] == USER
    call = host.activation.provision.await_args.kwargs
    assert call["authorized_plan"] == "trusted-plan"
    assert call["session_id"] == auth["session_id"]
    assert call["tenant_id"] == TENANT and call["user_id"] == USER


@pytest.mark.parametrize("credential", [
    "123456:raw_bot_token",
    "bot-token",
    "",
    "vault://missing:rawsecret",
    "vault://has whitespace",
    "vault://11111111-1111-1111-1111-111111111111:rawtoken",
    "vault://11111111-1111-1111-1111-11111111111A",
])
def test_telegram_provision_request_rejects_raw_credentials(credential):
    with pytest.raises(ValidationError):
        api.TelegramProvisionRequest(
            provider_account_id="account", credential_handle=credential,
        )


@pytest.mark.asyncio
async def test_telegram_provision_denies_policy_before_persistence():
    host, request = host_context()
    host.activation.provision = AsyncMock()
    host.activation.issue_action_plan.side_effect = PermissionError("not authorized")
    with pytest.raises(HTTPException) as error:
        await api.provision_telegram_connection(
            payload=api.TelegramProvisionRequest(
                provider_account_id="account",
                credential_handle="vault://11111111-1111-1111-1111-111111111111",
            ),
            request=request, user=actor(),
        )
    assert error.value.status_code == 403
    host.activation.provision.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_provision_cannot_claim_activated_connection():
    host, request = host_context()
    host.activation.provision = AsyncMock(return_value=ChannelConnection(
        connection_id=CONNECTION, tenant_id=TENANT,
        installation_id="telegram-bot", provider_account_id="account",
        credential_handle="vault://ref", revision=2, enabled=True,
    ))
    with pytest.raises(HTTPException) as error:
        await api.provision_telegram_connection(
            payload=api.TelegramProvisionRequest(
                provider_account_id="account",
                credential_handle="vault://11111111-1111-1111-1111-111111111111",
            ),
            request=request, user=actor(roles=["admin"]),
        )
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_telegram_provision_ignores_untrusted_actor_fields_and_refuses_foreign_result():
    host, request = host_context()
    host.activation.provision = AsyncMock(return_value=ChannelConnection(
        connection_id=CONNECTION, tenant_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
        installation_id="telegram-bot", provider_account_id="account",
        credential_handle="vault://ref", revision=1, enabled=False,
    ))
    with pytest.raises(HTTPException) as error:
        await api.provision_telegram_connection(
            payload=api.TelegramProvisionRequest(
                provider_account_id="account", credential_handle="vault://11111111-1111-1111-1111-111111111111",
            ),
            request=request, user=actor(roles=["admin"]),
        )
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_telegram_activation_uses_existing_runtime_policy_and_local_evidence_only():
    host, request = host_context()
    host.repository.get_connection = AsyncMock(return_value=ChannelConnection(
        connection_id=CONNECTION, tenant_id=TENANT,
        installation_id="telegram-bot", provider_account_id="account",
        credential_handle="vault://11111111-1111-1111-1111-111111111111",
        revision=1, enabled=False,
    ))
    host.activate_telegram_connection = AsyncMock(return_value=ChannelConnection(
        connection_id=CONNECTION, tenant_id=TENANT,
        installation_id="telegram-bot", provider_account_id="account",
        credential_handle="vault://11111111-1111-1111-1111-111111111111",
        revision=2, enabled=True,
    ))
    result = await api.activate_telegram_connection(
        connection_id=api.UUID(CONNECTION),
        payload=api.TelegramActivationRequest(expected_revision=1),
        request=request, user=actor(roles=["admin"]),
    )
    assert result.enabled is True
    assert result.revision == 2
    assert result.provider_identity_verified_at_activation is True
    assert result.webhook_registration_verified is False
    assert result.live_connected is False
    assert "vault://" not in result.model_dump_json()
    plan = host.activation.issue_action_plan.await_args.kwargs
    call = host.activate_telegram_connection.await_args.kwargs
    assert plan["action"] == "channel.activate"
    assert plan["tenant_id"] == TENANT and plan["user_id"] == USER
    assert call["session_id"] == plan["session_id"]
    assert call["authorized_plan"] == "trusted-plan"
    assert call["expected_revision"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("revision,enabled,installation", [
    (2, False, "telegram-bot"),
    (1, True, "telegram-bot"),
    (1, False, "whatsapp-cloud"),
])
async def test_telegram_activation_rejects_unavailable_connection_before_policy(
    revision, enabled, installation,
):
    host, request = host_context()
    host.repository.get_connection = AsyncMock(return_value=ChannelConnection(
        connection_id=CONNECTION, tenant_id=TENANT, installation_id=installation,
        provider_account_id="account",
        credential_handle="vault://11111111-1111-1111-1111-111111111111",
        revision=revision, enabled=enabled,
    ))
    host.activate_telegram_connection = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await api.activate_telegram_connection(
            connection_id=api.UUID(CONNECTION),
            payload=api.TelegramActivationRequest(expected_revision=1),
            request=request, user=actor(roles=["admin"]),
        )
    assert error.value.status_code == 403
    host.activation.issue_action_plan.assert_not_awaited()
    host.activate_telegram_connection.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_activation_policy_denial_cannot_start_adapter():
    host, request = host_context()
    host.repository.get_connection = AsyncMock(return_value=ChannelConnection(
        connection_id=CONNECTION, tenant_id=TENANT, installation_id="telegram-bot",
        provider_account_id="account",
        credential_handle="vault://11111111-1111-1111-1111-111111111111",
        revision=1, enabled=False,
    ))
    host.activate_telegram_connection = AsyncMock()
    host.activation.issue_action_plan.side_effect = PermissionError("not allowed")
    with pytest.raises(HTTPException) as error:
        await api.activate_telegram_connection(
            connection_id=api.UUID(CONNECTION),
            payload=api.TelegramActivationRequest(expected_revision=1),
            request=request, user=actor(),
        )
    assert error.value.status_code == 403
    host.activate_telegram_connection.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_activation_rejects_fake_provider_readiness_result():
    host, request = host_context()
    host.repository.get_connection = AsyncMock(return_value=ChannelConnection(
        connection_id=CONNECTION, tenant_id=TENANT, installation_id="telegram-bot",
        provider_account_id="account",
        credential_handle="vault://11111111-1111-1111-1111-111111111111",
        revision=1, enabled=False,
    ))
    host.activate_telegram_connection = AsyncMock(return_value=ChannelConnection(
        connection_id=CONNECTION, tenant_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        installation_id="telegram-bot", provider_account_id="account",
        credential_handle="vault://11111111-1111-1111-1111-111111111111",
        revision=2, enabled=True,
    ))
    with pytest.raises(HTTPException) as error:
        await api.activate_telegram_connection(
            connection_id=api.UUID(CONNECTION),
            payload=api.TelegramActivationRequest(expected_revision=1),
            request=request, user=actor(roles=["admin"]),
        )
    assert error.value.status_code == 503


@pytest.mark.parametrize("bad", [0, -1, True, "1", 1.0])
def test_telegram_activation_requires_strict_positive_revision(bad):
    with pytest.raises(ValidationError):
        api.TelegramActivationRequest(expected_revision=bad)
