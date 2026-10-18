"""Self-service QR risk consent API: authenticated owner, no fake pairing."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
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
    host.repository = SimpleNamespace(
        get_connection=AsyncMock(return_value=ChannelConnection(
            connection_id=CONNECTION, tenant_id=TENANT,
            installation_id="whatsapp-cloud", provider_account_id="account",
            credential_handle="vault://ref", revision=1, enabled=False,
        )),
        is_personal_connection_owner=AsyncMock(return_value=owner),
    )
    host.get_personal_pairing_risk = AsyncMock(return_value=None)
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
