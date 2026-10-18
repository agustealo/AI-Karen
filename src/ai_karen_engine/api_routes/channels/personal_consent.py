"""Authenticated, thin personal-channel risk consent ingress.

Never accepts actor identity, session, policy plan, or connection owner claims
from HTTP input. No QR, linked device, or provider session is created here.
"""
from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.channels.host import ChannelHostServices
from ai_karen_engine.services.channels.personal_pairing_policy import (
    PERSONAL_WHATSAPP_CONSENT_VERSION,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/channels/personal", tags=["communication-channels"])


class RiskAcknowledgement(BaseModel):
    accepted: bool
    policy_version: str


class ConsentResult(BaseModel):
    acknowledged: bool = False
    revoked: bool = False
    paired: bool = False
    provider_unlinked: bool = False


def _host_and_actor(request: Request, user: UserData) -> tuple[ChannelHostServices, str, str]:
    tenant_id = str(user.tenant_id or "").strip()
    user_id = str(user.user_id or "").strip()
    try:
        tenant_id, user_id = str(UUID(tenant_id)), str(UUID(user_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(403, "Verified durable user and tenant identity required") from None
    if user.is_active is not True or user.is_verified is not True:
        raise HTTPException(403, "Active verified user required")
    host = getattr(request.app.state, "channel_host_services", None)
    if not isinstance(host, ChannelHostServices) or host.activation is None:
        raise HTTPException(503, "Channel consent service unavailable")
    return host, tenant_id, user_id


async def _authorize(
    *, host: ChannelHostServices, tenant_id: str, user_id: str,
    connection_id: str,
) -> tuple[str, object]:
    """Mint a one-action context; runtime owns actual authorization."""
    connection = await host.repository.get_connection(
        tenant_id=tenant_id, connection_id=connection_id,
    )
    if (
        connection is None
        or connection.tenant_id != tenant_id
        or connection.connection_id != connection_id
        or not await host.repository.is_personal_connection_owner(
            tenant_id=tenant_id, connection_id=connection_id, user_id=user_id,
        )
    ):
        raise PermissionError("Personal connection not assigned to this user")
    session_id = str(uuid4())
    plan = await host.activation.issue_action_plan(
        tenant_id=tenant_id, user_id=user_id, session_id=session_id,
        installation_id=connection.installation_id, action="channel.consent",
    )
    return session_id, plan


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(403, "Personal channel consent denied")
    if isinstance(exc, ValueError):
        return HTTPException(422, "Invalid personal channel consent request")
    logger.error(
        "channel.personal_consent.unavailable",
        extra={"error_type": type(exc).__name__},
    )
    return HTTPException(503, "Personal channel consent unavailable")


@router.post("/{connection_id}/{provider_id}/consent", response_model=ConsentResult)
async def acknowledge_personal_whatsapp_risk(
    connection_id: UUID,
    provider_id: str,
    payload: RiskAcknowledgement,
    request: Request,
    user: UserData = Depends(get_current_user),
) -> ConsentResult:
    """Accept versioned risk only for caller's assigned durable connection."""
    if payload.accepted is not True or payload.policy_version != PERSONAL_WHATSAPP_CONSENT_VERSION:
        raise HTTPException(422, "Current risk notice must be explicitly accepted")
    if not provider_id or len(provider_id) > 128:
        raise HTTPException(422, "Invalid managed provider identifier")
    host, tenant_id, user_id = _host_and_actor(request, user)
    try:
        session_id, plan = await _authorize(
            host=host, tenant_id=tenant_id, user_id=user_id,
            connection_id=str(connection_id),
        )
        written = await host.acknowledge_personal_pairing_risk(
            tenant_id=tenant_id, connection_id=str(connection_id),
            user_id=user_id, session_id=session_id, provider_id=provider_id,
            accepted=True, policy_version=payload.policy_version,
            authorized_plan=plan,
        )
    except Exception as exc:
        raise _translate(exc) from None
    return ConsentResult(acknowledged=written)


@router.post("/{connection_id}/{provider_id}/revoke", response_model=ConsentResult)
async def revoke_personal_whatsapp_risk(
    connection_id: UUID,
    provider_id: str,
    request: Request,
    user: UserData = Depends(get_current_user),
) -> ConsentResult:
    """Revoke policy consent, without claiming external device unlink."""
    if not provider_id or len(provider_id) > 128:
        raise HTTPException(422, "Invalid managed provider identifier")
    host, tenant_id, user_id = _host_and_actor(request, user)
    try:
        session_id, plan = await _authorize(
            host=host, tenant_id=tenant_id, user_id=user_id,
            connection_id=str(connection_id),
        )
        revoked = await host.revoke_personal_pairing_risk(
            tenant_id=tenant_id, connection_id=str(connection_id),
            user_id=user_id, session_id=session_id,
            provider_id=provider_id, authorized_plan=plan,
        )
    except Exception as exc:
        raise _translate(exc) from None
    return ConsentResult(revoked=revoked)


__all__ = ["router"]
