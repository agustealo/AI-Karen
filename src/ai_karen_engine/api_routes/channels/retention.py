"""Authenticated operator ingress for WhatsApp status-evidence retention.

No provider callback, plugin execution, client-supplied user identity, secret,
retention duration, or policy grant is accepted here. ChatRuntime is untouched.
"""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool, model_validator

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.channels.host import ChannelHostServices

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/channels", tags=["communication-channels"])


class StatusRetentionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: StrictBool
    confirm_prune: StrictBool = False

    @model_validator(mode="after")
    def confirm_destructive_request(self) -> "StatusRetentionRequest":
        if not self.dry_run and not self.confirm_prune:
            raise ValueError("Destructive status pruning requires confirmation")
        return self


class StatusRetentionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool
    eligible_count: int
    deleted_count: int
    connection_revision: int
    retention_days: int
    batch_limit: int


@router.post(
    "/{connection_id}/status-retention",
    response_model=StatusRetentionResult,
)
async def prune_whatsapp_status_evidence(
    connection_id: UUID,
    payload: StatusRetentionRequest,
    request: Request,
    user: UserData = Depends(get_current_user),
) -> StatusRetentionResult:
    """Issue one fresh RBAC/RuntimePolicy plan for this operator and connection."""
    try:
        tenant_id = str(UUID(str(user.tenant_id or "")))
        user_id = str(UUID(str(user.user_id or "")))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(403, "Verified tenant operator required") from None
    if user.is_active is not True or user.is_verified is not True:
        raise HTTPException(403, "Active verified operator required")
    host = getattr(request.app.state, "channel_host_services", None)
    if not isinstance(host, ChannelHostServices) or host.activation is None:
        raise HTTPException(503, "Channel status retention unavailable")
    try:
        connection = await host.repository.get_connection(
            tenant_id=tenant_id, connection_id=str(connection_id),
        )
        if (
            connection is None or connection.tenant_id != tenant_id
            or connection.connection_id != str(connection_id)
            or connection.installation_id != "whatsapp-cloud"
        ):
            raise PermissionError("WhatsApp channel does not belong to this tenant")
        session_id = str(uuid4())
        plan = await host.activation.issue_action_plan(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.status_prune",
        )
        result = await host.prune_unmatched_whatsapp_statuses(
            tenant_id=tenant_id, connection_id=str(connection_id),
            user_id=user_id, session_id=session_id,
            authorized_plan=plan, dry_run=payload.dry_run,
        )
    except PermissionError:
        raise HTTPException(403, "Status retention denied") from None
    except ValueError:
        raise HTTPException(422, "Invalid status retention request") from None
    except Exception as exc:
        logger.error(
            "channel.status_retention.unavailable",
            extra={"error_type": type(exc).__name__,
                   "tenant_id": tenant_id,
                   "connection_id": str(connection_id)},
        )
        raise HTTPException(503, "Status retention unavailable") from None
    return StatusRetentionResult.model_validate(result)


__all__ = [
    "StatusRetentionRequest", "StatusRetentionResult",
    "prune_whatsapp_status_evidence", "router",
]
