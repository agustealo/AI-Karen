"""Thin authenticated ingress for one-time, host-owned channel identity linking.

Only the existing ChannelLinkService mints proof bytes and persists their
digest. This API cannot link an arbitrary sender or select a Karen principal;
a separately signed provider /link POST must consume the one-time proof.
"""
from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ai_karen_engine.api_routes.channels.personal_consent import _verified_actor
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.channels.host import ChannelHostServices
from ai_karen_engine.services.channels.linking import ChannelLinkConflict

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/channels/identity/whatsapp",
    tags=["communication-channels"],
)


class WhatsAppSelfLinkRequest(BaseModel):
    """No client-chosen policy plan, principal, secret, TTL or sender."""

    model_config = ConfigDict(extra="forbid")


class WhatsAppSelfLinkChallenge(BaseModel):
    """Delivered to the authenticated account once; never a durable token view."""

    model_config = ConfigDict(extra="forbid")

    challenge_id: UUID
    command: str = Field(pattern=r"^/link [A-Za-z0-9_-]{43}$")
    expires_in_seconds: int = Field(ge=60, le=900)


@router.post(
    "/connections/{connection_id}/challenge",
    status_code=201,
    response_model=WhatsAppSelfLinkChallenge,
)
async def issue_whatsapp_self_link_challenge(
    connection_id: UUID,
    request: Request,
    response: Response,
    _payload: WhatsAppSelfLinkRequest | None = Body(default=None),
    user: UserData = Depends(get_current_user),
) -> WhatsAppSelfLinkChallenge:
    """Issue one digest-backed proof for the signed-in verified Karen user."""

    # Prevent any browser/intermediary reuse of the returned bearer proof.
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    tenant_id, user_id = _verified_actor(user)
    host = getattr(request.app.state, "channel_host_services", None)
    if not isinstance(host, ChannelHostServices) or host.activation is None:
        raise HTTPException(503, "WhatsApp identity linking unavailable")

    session_id = str(uuid4())
    try:
        plan = await host.activation.issue_action_plan(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id="whatsapp-cloud", action="channel.link",
        )
        issued = await host.issue_whatsapp_self_link_challenge(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            connection_id=str(connection_id), authorized_plan=plan,
        )
        return WhatsAppSelfLinkChallenge.model_validate({
            "challenge_id": issued.challenge_id,
            "command": issued.command,
            "expires_in_seconds": issued.expires_in_seconds,
        })
    except PermissionError:
        raise HTTPException(403, "WhatsApp identity linking denied") from None
    except ChannelLinkConflict:
        raise HTTPException(409, "WhatsApp identity linking conflict") from None
    except ValueError:
        raise HTTPException(422, "Invalid WhatsApp identity linking request") from None
    except Exception as exc:
        # The one-time secret is not logged, nor are upstream/provider payloads.
        logger.error(
            "channel.identity.challenge_unavailable",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(503, "WhatsApp identity linking unavailable") from None


__all__ = ["WhatsAppSelfLinkChallenge", "WhatsAppSelfLinkRequest", "issue_whatsapp_self_link_challenge", "router"]
