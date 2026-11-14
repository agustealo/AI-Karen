"""Authenticated, thin personal-channel risk consent ingress.

Never accepts actor identity, session, policy plan, or connection owner claims
from HTTP input. No QR, linked device, or provider session is created here.
"""
from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.channels.host import ChannelHostServices
from ai_karen_engine.persistence.repositories.channel_repository import (
    ChannelRetirementConflict,
)
from ai_karen_engine.services.channels.consent_recovery import (
    PersonalConsentRecoveryService,
)
from ai_karen_engine.services.channels.personal_pairing_policy import (
    PERSONAL_WHATSAPP_CONSENT_VERSION,
    PERSONAL_WHATSAPP_RISK_NOTICE_TEXT,
    PERSONAL_WHATSAPP_RISK_NOTICE_TITLE,
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


class PersonalOwnerAssignment(BaseModel):
    """Only the target owner is supplied; actor and tenant come from auth."""

    model_config = ConfigDict(extra="forbid")

    owner_user_id: UUID


class PersonalOwnerAssignmentResult(BaseModel):
    owner_assigned: bool
    paired: bool = False
    qr_available: bool = False
    provider_unlinked: bool = False


def _verified_actor(user: UserData) -> tuple[str, str]:
    """One auth-derived durable actor shared by host and recovery ingress."""
    tenant_id = str(user.tenant_id or "").strip()
    user_id = str(user.user_id or "").strip()
    try:
        tenant_id, user_id = str(UUID(tenant_id)), str(UUID(user_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(403, "Verified durable user and tenant identity required") from None
    if user.is_active is not True or user.is_verified is not True:
        raise HTTPException(403, "Active verified user required")
    return tenant_id, user_id


def _host_and_actor(request: Request, user: UserData) -> tuple[ChannelHostServices, str, str]:
    tenant_id, user_id = _verified_actor(user)
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


def _translate(
    exc: Exception, *, operation: Literal["consent", "ownership", "recovery", "retirement"] = "consent",
) -> HTTPException:
    label = {
        "ownership": "Personal channel ownership",
        "consent": "Personal channel consent",
        "recovery": "Personal channel consent recovery",
        "retirement": "Personal channel retirement hold",
    }[operation]
    if isinstance(exc, PermissionError):
        return HTTPException(403, f"{label} denied")
    if isinstance(exc, ValueError):
        return HTTPException(422, f"Invalid {label.lower()} request")
    logger.error(
        {
            "ownership": "channel.personal_owner_assignment.unavailable",
            "consent": "channel.personal_consent.unavailable",
            "recovery": "channel.personal_consent.recovery_unavailable",
            "retirement": "channel.personal_retirement.unavailable",
        }[operation],
        extra={"error_type": type(exc).__name__},
    )
    return HTTPException(503, f"{label} unavailable")


@router.post(
    "/{connection_id}/owner",
    status_code=201,
    response_model=PersonalOwnerAssignmentResult,
)
async def assign_personal_channel_owner(
    connection_id: UUID,
    payload: PersonalOwnerAssignment,
    request: Request,
    user: UserData = Depends(get_current_user),
) -> PersonalOwnerAssignmentResult:
    """Assign an existing connection once through canonical operator authority.

    No provider pairing, QR issuance, transport activation or secret handling.
    The session actor and tenant are derived only from authenticated identity;
    the target owner is independently checked as active and verified by SQL.
    """
    host, tenant_id, operator_user_id = _host_and_actor(request, user)
    try:
        connection = await host.repository.get_connection(
            tenant_id=tenant_id, connection_id=str(connection_id),
        )
        if (
            connection is None
            or connection.tenant_id != tenant_id
            or connection.connection_id != str(connection_id)
        ):
            raise PermissionError("Connection outside operator tenant")

        # The personal endpoint cannot assign owners to generic channel
        # installations. The managed operator must be explicitly allowlisted
        # with a Vault-backed signing-secret contract before provisioning.
        # This is an eligibility gate, not evidence of a live paired session.
        installation_id = connection.installation_id
        if (
            not host.settings.personal_pairing_providers.get(installation_id)
            or "pairing_webhook_secret"
            not in host.settings.installations.get(installation_id, frozenset())
        ):
            raise PermissionError("Managed personal provider unavailable")

        session_id = str(uuid4())
        plan = await host.activation.issue_action_plan(
            tenant_id=tenant_id,
            user_id=operator_user_id,
            session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.provision",
        )
        assigned = await host.assign_personal_connection_owner(
            tenant_id=tenant_id,
            connection_id=str(connection_id),
            owner_user_id=str(payload.owner_user_id),
            operator_user_id=operator_user_id,
            session_id=session_id,
            authorized_plan=plan,
        )
    except Exception as exc:
        raise _translate(exc, operation="ownership") from None

    # SQL returns False for an existing, conflicting, or ineligible owner.
    # Never claim reassignment, connection success or provider unlink.
    if assigned is not True:
        raise HTTPException(409, "Connection owner not assigned")
    return PersonalOwnerAssignmentResult(owner_assigned=True)


class PersonalRetirementHoldRequest(BaseModel):
    """Only optimistic revision and idempotency originate from the client."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1, strict=True)
    idempotency_key: UUID


class PersonalRetirementHoldResult(BaseModel):
    hold_id: UUID
    connection_revision: int
    hold_recorded: bool
    connection_enabled: bool
    created_new: bool
    local_stop_attempted: bool
    local_stop_succeeded: bool
    provider_unlinked: bool
    credentials_erased: bool


@router.post(
    "/{connection_id}/retirement-hold",
    response_model=PersonalRetirementHoldResult,
)
async def place_personal_retirement_hold(
    connection_id: UUID,
    payload: PersonalRetirementHoldRequest,
    request: Request,
    user: UserData = Depends(get_current_user),
) -> PersonalRetirementHoldResult:
    """Explicit operator hold, never remote unlink or deletion authorization."""
    host, tenant_id, operator_user_id = _host_and_actor(request, user)
    try:
        connection = await host.repository.get_connection(
            tenant_id=tenant_id, connection_id=str(connection_id),
        )
        if (
            connection is None
            or connection.tenant_id != tenant_id
            or connection.connection_id != str(connection_id)
        ):
            raise PermissionError("Retirement connection outside operator tenant")
        session_id = str(uuid4())
        plan = await host.activation.issue_action_plan(
            tenant_id=tenant_id, user_id=operator_user_id,
            session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.deactivate",
        )
        outcome = await host.place_personal_retirement_hold(
            tenant_id=tenant_id, connection_id=str(connection_id),
            operator_user_id=operator_user_id, session_id=session_id,
            authorized_plan=plan,
            expected_revision=payload.expected_revision,
            idempotency_key=str(payload.idempotency_key),
        )
    except ChannelRetirementConflict:
        raise HTTPException(409, "Personal channel retirement revision conflict") from None
    except Exception as exc:
        raise _translate(exc, operation="retirement") from None
    return PersonalRetirementHoldResult(**outcome)


class PersonalPairingStatus(BaseModel):
    availability: str
    last_observed_phase: str | None = None
    live_connected: bool = False
    qr_available: bool = False
    provider_unlinked: bool = False


class PersonalChannelInventoryItem(PersonalPairingStatus):
    connection_id: str
    installation_id: str
    provider_id: str | None = None
    active_consent_provider_ids: list[str]


class PersonalChannelInventoryResponse(BaseModel):
    connections: list[PersonalChannelInventoryItem]


@router.get("/connections", response_model=PersonalChannelInventoryResponse)
async def list_personal_channel_connections(
    request: Request,
    user: UserData = Depends(get_current_user),
) -> PersonalChannelInventoryResponse:
    """Show only the caller's assigned channels; never expose credentials.

    No caller may select tenant, owner, installation or provider via query.
    The host performs fresh per-installation policy and exact owner checks.
    """
    host, tenant_id, user_id = _host_and_actor(request, user)
    try:
        connections = await host.list_owned_personal_channels(
            tenant_id=tenant_id, user_id=user_id,
        )
    except Exception as exc:
        raise _translate(exc) from None
    return PersonalChannelInventoryResponse(connections=connections)


class PersonalConsentRecoveryItem(BaseModel):
    connection_id: str
    provider_id: str
    policy_version: str


class PersonalConsentRecoveryInventory(BaseModel):
    consents: list[PersonalConsentRecoveryItem]


class PersonalRetirementEvidenceItem(BaseModel):
    connection_id: str
    connection_revision: int
    connection_enabled: bool
    retirement_held: bool
    active_consent: bool
    unresolved_pairing: bool
    deletion_request_recorded: bool
    unverified_deletion_request: bool
    inbox_not_completed: bool
    outbound_not_confirmed: bool


class PersonalRetirementEvidenceInventory(BaseModel):
    connections: list[PersonalRetirementEvidenceItem]


@router.get(
    "/consent-recovery/retirement-evidence",
    response_model=PersonalRetirementEvidenceInventory,
)
async def list_retired_channel_evidence(
    user: UserData = Depends(get_current_user),
) -> PersonalRetirementEvidenceInventory:
    """Owner-scoped SQL observations, never a retirement authorization."""
    tenant_id, user_id = _verified_actor(user)
    try:
        rows = await PersonalConsentRecoveryService().list_retirement_evidence(
            tenant_id=tenant_id, user_id=user_id,
        )
    except Exception as exc:
        raise _translate(exc, operation="recovery") from None
    return PersonalRetirementEvidenceInventory(connections=rows)


class PersonalCredentialDeletionRequestItem(BaseModel):
    request_id: UUID
    connection_id: str
    provider_id: str
    connection_revision: int
    status: Literal[
        "requested", "provider_pending", "provider_claimed",
        "verification_pending", "verified", "unknown",
    ]


class PersonalCredentialDeletionInventory(BaseModel):
    requests: list[PersonalCredentialDeletionRequestItem]


@router.get(
    "/consent-recovery/deletion-requests",
    response_model=PersonalCredentialDeletionInventory,
)
async def list_retired_credential_deletion_requests(
    user: UserData = Depends(get_current_user),
) -> PersonalCredentialDeletionInventory:
    """Show stored deletion intent; never assert provider or local erasure."""
    tenant_id, user_id = _verified_actor(user)
    try:
        rows = await PersonalConsentRecoveryService().list_deletion_requests(
            tenant_id=tenant_id, user_id=user_id,
        )
    except Exception as exc:
        raise _translate(exc, operation="recovery") from None
    return PersonalCredentialDeletionInventory(requests=rows)


@router.get("/consent-recovery", response_model=PersonalConsentRecoveryInventory)
async def list_personal_consent_recovery(
    user: UserData = Depends(get_current_user),
) -> PersonalConsentRecoveryInventory:
    """Owner-scoped SQL consent ledger, even without a channel installation.

    This is not a new ChannelHost or provider readiness endpoint.
    """
    tenant_id, user_id = _verified_actor(user)
    try:
        rows = await PersonalConsentRecoveryService().list_active(
            tenant_id=tenant_id, user_id=user_id,
        )
    except Exception as exc:
        raise _translate(exc, operation="recovery") from None
    return PersonalConsentRecoveryInventory(consents=rows)


@router.post(
    "/consent-recovery/{connection_id}/{provider_id}/revoke",
    response_model=ConsentResult,
)
async def revoke_retired_personal_consent(
    connection_id: UUID,
    provider_id: str,
    user: UserData = Depends(get_current_user),
) -> ConsentResult:
    """Only withdraw existing stored consent; never assert remote unlink."""
    if not provider_id or not provider_id.strip() or len(provider_id) > 128:
        raise HTTPException(422, "Invalid consent recovery provider")
    tenant_id, user_id = _verified_actor(user)
    try:
        revoked = await PersonalConsentRecoveryService().revoke(
            tenant_id=tenant_id,
            user_id=user_id,
            connection_id=str(connection_id),
            provider_id=provider_id,
        )
    except Exception as exc:
        raise _translate(exc, operation="recovery") from None
    return ConsentResult(revoked=revoked)


@router.get("/{connection_id}/{provider_id}/status", response_model=PersonalPairingStatus)
async def get_personal_whatsapp_pairing_status(
    connection_id: UUID,
    provider_id: str,
    request: Request,
    user: UserData = Depends(get_current_user),
) -> PersonalPairingStatus:
    """Read history without implying managed-provider health or a live QR."""
    if not provider_id or len(provider_id) > 128:
        raise HTTPException(422, "Invalid managed provider identifier")
    host, tenant_id, user_id = _host_and_actor(request, user)
    try:
        session_id, plan = await _authorize(
            host=host, tenant_id=tenant_id, user_id=user_id,
            connection_id=str(connection_id),
        )
        result = await host.get_personal_pairing_status(
            tenant_id=tenant_id, connection_id=str(connection_id),
            provider_id=provider_id, user_id=user_id,
            session_id=session_id, authorized_plan=plan,
        )
    except Exception as exc:
        raise _translate(exc) from None
    return PersonalPairingStatus(**result)


class ConsentStatus(BaseModel):
    acknowledged: bool
    has_active_consent: bool
    policy_version: str
    notice_title: str
    notice_text: str
    paired: bool = False
    provider_unlinked: bool = False


@router.get("/{connection_id}/{provider_id}/consent", response_model=ConsentStatus)
async def get_personal_whatsapp_risk_status(
    connection_id: UUID,
    provider_id: str,
    request: Request,
    user: UserData = Depends(get_current_user),
) -> ConsentStatus:
    """Read only the caller's current persisted consent, not pairing status."""
    if not provider_id or len(provider_id) > 128:
        raise HTTPException(422, "Invalid managed provider identifier")
    host, tenant_id, user_id = _host_and_actor(request, user)
    try:
        session_id, plan = await _authorize(
            host=host, tenant_id=tenant_id, user_id=user_id,
            connection_id=str(connection_id),
        )
        consent = await host.get_personal_pairing_risk(
            tenant_id=tenant_id, connection_id=str(connection_id),
            user_id=user_id, session_id=session_id,
            provider_id=provider_id, authorized_plan=plan,
        )
    except Exception as exc:
        raise _translate(exc) from None
    active = (
        consent is not None
        and consent.tenant_id == tenant_id
        and consent.user_id == user_id
        and consent.connection_id == str(connection_id)
        and consent.provider_id == provider_id
        and consent.revoked_at is None
    )
    return ConsentStatus(
        acknowledged=active and consent.policy_version == PERSONAL_WHATSAPP_CONSENT_VERSION,
        has_active_consent=active,
        policy_version=PERSONAL_WHATSAPP_CONSENT_VERSION,
        notice_title=PERSONAL_WHATSAPP_RISK_NOTICE_TITLE,
        notice_text=PERSONAL_WHATSAPP_RISK_NOTICE_TEXT,
    )


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
