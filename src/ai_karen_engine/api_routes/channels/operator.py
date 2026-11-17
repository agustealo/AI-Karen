"""Authenticated operator ingress for a single governed WhatsApp Cloud connection.

This route never selects a plugin adapter, reads secrets, builds RuntimePolicy
grants, calls Meta, or claims live webhook/delivery verification. The canonical
ChannelHostServices, ChannelActivationService and Identity Vault own execution.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from ai_karen_engine.api_routes.channels.personal_consent import _verified_actor
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.channels.activation import ChannelActivationConflict
from ai_karen_engine.services.channels.host import ChannelHostServices

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/channels/operator/whatsapp",
    tags=["communication-channels"],
)


class WhatsAppConnectionState(BaseModel):
    """Persisted local state only, not a provider reachability attestation."""

    model_config = ConfigDict(extra="forbid")

    connection_id: UUID
    connection_revision: StrictInt = Field(ge=1)
    enabled: bool


class WhatsAppInventoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connections: list[WhatsAppConnectionState] = Field(max_length=50)


class WhatsAppProvisionRequest(BaseModel):
    """Provider identity and opaque Vault reference, never secret bytes."""

    model_config = ConfigDict(extra="forbid")

    provider_account_id: str = Field(min_length=1, max_length=32, pattern=r"^[0-9]{1,32}$")
    credential_handle: str = Field(min_length=1, max_length=256)


class WhatsAppTrialInspectionRequest(BaseModel):
    """Provider inbound ID arrives in JSON, never a URL or log line."""

    model_config = ConfigDict(extra="forbid")

    external_event_id: str = Field(
        min_length=7, max_length=256,
        pattern=r"^wamid\.[A-Za-z0-9._+=/-]{1,250}$",
    )


class WhatsAppTrialEvidenceResponse(BaseModel):
    """Historical host-persisted facts, never independent Meta certification."""

    model_config = ConfigDict(extra="forbid")

    connection_revision: StrictInt = Field(ge=1)
    current_connection_revision: StrictInt = Field(ge=1)
    connection_enabled: bool
    inbox_id: UUID
    correlation_id: UUID
    inbox_status: Literal["pending", "processing", "completed", "failed"]
    binding_currently_active: bool
    outbound_delivery_id: UUID | None = None
    outbound_status: Literal[
        "accepted", "sent", "delivered", "read", "failed", "unknown"
    ] | None = None
    outbound_provider_message_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$",
    )
    provider_receipt_states: tuple[
        Literal["sent", "delivered", "read", "failed"], ...
    ] = ()
    evidence_basis: Literal["host_persisted_lineage_only"] = "host_persisted_lineage_only"
    meta_origin_independently_verified: Literal[False] = False
    consumer_certified: Literal[False] = False


class WhatsAppRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: StrictInt = Field(ge=1)


class WhatsAppOperationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: str
    connection_revision: int
    enabled: bool
    stage: Literal["provisioned", "activated", "deactivated"]
    provider_phone_verified: bool
    webhook_subscription_verified: bool = False
    signed_inbound_verified: bool = False
    delivery_verified: bool = False


def _operator(request: Request, user: UserData) -> tuple[ChannelHostServices, str, str]:
    tenant_id, user_id = _verified_actor(user)
    host = getattr(request.app.state, "channel_host_services", None)
    if not isinstance(host, ChannelHostServices) or host.activation is None:
        raise HTTPException(503, "WhatsApp operator host unavailable")
    return host, tenant_id, user_id


def _result(
    connection: object, *, tenant_id: str, connection_id: str | None,
    stage: Literal["provisioned", "activated", "deactivated"],
) -> WhatsAppOperationResult:
    observed_id = str(getattr(connection, "connection_id", ""))
    if (
        str(getattr(connection, "tenant_id", "")) != tenant_id
        or str(getattr(connection, "installation_id", "")) != "whatsapp-cloud"
        or not observed_id
        or (connection_id is not None and observed_id != connection_id)
        or type(getattr(connection, "revision", None)) is not int
        or getattr(connection, "revision") < 1
        or type(getattr(connection, "enabled", None)) is not bool
        or getattr(connection, "enabled") is not (stage == "activated")
    ):
        raise RuntimeError("WhatsApp persistence returned a mismatched connection")
    return WhatsAppOperationResult(
        connection_id=observed_id,
        connection_revision=connection.revision,
        enabled=connection.enabled,
        stage=stage,
        provider_phone_verified=stage == "activated",
    )


def _translate(exc: Exception, *, operation: str) -> HTTPException:
    if isinstance(exc, ValidationError):
        logger.error(
            "channel.whatsapp_operator.invalid_backend_inventory",
            extra={"operation": operation},
        )
        return HTTPException(503, "WhatsApp operator inventory unavailable")
    if isinstance(exc, ChannelActivationConflict):
        return HTTPException(409, "WhatsApp connection changed; reload its revision")
    if isinstance(exc, PermissionError):
        return HTTPException(403, "WhatsApp operator action denied")
    if isinstance(exc, ValueError):
        return HTTPException(422, "Invalid WhatsApp operator request")
    logger.error(
        "channel.whatsapp_operator.unavailable",
        extra={"operation": operation, "error_type": type(exc).__name__},
    )
    return HTTPException(503, "WhatsApp operator action unavailable")


@router.get("/connections", response_model=WhatsAppInventoryResponse)
async def list_whatsapp_connections(
    request: Request, user: UserData = Depends(get_current_user),
) -> WhatsAppInventoryResponse:
    host, tenant_id, user_id = _operator(request, user)
    session_id = str(uuid4())
    try:
        plan = await host.activation.issue_action_plan(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id="whatsapp-cloud", action="channel.inspect",
        )
        connections = await host.list_whatsapp_operator_connections(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            authorized_plan=plan,
        )
        return WhatsAppInventoryResponse.model_validate(
            {"connections": connections},
        )
    except Exception as exc:
        raise _translate(exc, operation="inspect") from None


@router.post(
    "/connections/{connection_id}/trial-evidence",
    response_model=WhatsAppTrialEvidenceResponse,
)
async def inspect_whatsapp_trial_evidence(
    connection_id: UUID,
    payload: WhatsAppTrialInspectionRequest,
    request: Request,
    response: Response,
    user: UserData = Depends(get_current_user),
) -> WhatsAppTrialEvidenceResponse:
    """Read one verified host ledger chain; never perform an outbound action."""
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    host, tenant_id, user_id = _operator(request, user)
    session_id = str(uuid4())
    try:
        plan = await host.activation.issue_action_plan(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id="whatsapp-cloud", action="channel.inspect",
        )
        trial = await host.inspect_whatsapp_trial_evidence(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            connection_id=str(connection_id),
            external_event_id=payload.external_event_id,
            authorized_plan=plan,
        )
        if trial is None:
            raise HTTPException(404, "No persisted WhatsApp trial evidence")
        return WhatsAppTrialEvidenceResponse.model_validate(asdict(trial))
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc, operation="trial_inspection") from None


@router.post("/connections", status_code=201, response_model=WhatsAppOperationResult)
async def provision_whatsapp_connection(
    payload: WhatsAppProvisionRequest, request: Request,
    user: UserData = Depends(get_current_user),
) -> WhatsAppOperationResult:
    host, tenant_id, user_id = _operator(request, user)
    session_id = str(uuid4())
    try:
        plan = await host.activation.issue_action_plan(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id="whatsapp-cloud", action="channel.provision",
        )
        connection = await host.provision_whatsapp_connection(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            provider_account_id=payload.provider_account_id,
            credential_handle=payload.credential_handle,
            authorized_plan=plan,
        )
        return _result(connection, tenant_id=tenant_id, connection_id=None, stage="provisioned")
    except Exception as exc:
        raise _translate(exc, operation="provision") from None


@router.post(
    "/connections/{connection_id}/activate",
    response_model=WhatsAppOperationResult,
)
async def activate_whatsapp_connection(
    connection_id: UUID, payload: WhatsAppRevisionRequest, request: Request,
    user: UserData = Depends(get_current_user),
) -> WhatsAppOperationResult:
    host, tenant_id, user_id = _operator(request, user)
    session_id = str(uuid4())
    try:
        plan = await host.activation.issue_action_plan(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id="whatsapp-cloud", action="channel.activate",
        )
        connection = await host.activate_whatsapp_connection(
            tenant_id=tenant_id, connection_id=str(connection_id),
            user_id=user_id, session_id=session_id,
            authorized_plan=plan, expected_revision=payload.expected_revision,
        )
        return _result(
            connection, tenant_id=tenant_id, connection_id=str(connection_id),
            stage="activated",
        )
    except Exception as exc:
        raise _translate(exc, operation="activate") from None


@router.post(
    "/connections/{connection_id}/deactivate",
    response_model=WhatsAppOperationResult,
)
async def deactivate_whatsapp_connection(
    connection_id: UUID, payload: WhatsAppRevisionRequest, request: Request,
    user: UserData = Depends(get_current_user),
) -> WhatsAppOperationResult:
    host, tenant_id, user_id = _operator(request, user)
    session_id = str(uuid4())
    try:
        plan = await host.activation.issue_action_plan(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id="whatsapp-cloud", action="channel.deactivate",
        )
        connection = await host.deactivate_whatsapp_connection(
            tenant_id=tenant_id, connection_id=str(connection_id),
            user_id=user_id, session_id=session_id,
            authorized_plan=plan, expected_revision=payload.expected_revision,
        )
        return _result(
            connection, tenant_id=tenant_id, connection_id=str(connection_id),
            stage="deactivated",
        )
    except Exception as exc:
        raise _translate(exc, operation="deactivate") from None


__all__ = [
    "WhatsAppConnectionState",
    "WhatsAppInventoryResponse",
    "list_whatsapp_connections",
    "WhatsAppProvisionRequest",
    "WhatsAppRevisionRequest",
    "WhatsAppOperationResult",
    "provision_whatsapp_connection",
    "activate_whatsapp_connection",
    "deactivate_whatsapp_connection",
    "router",
]
