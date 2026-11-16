"""Authenticated, thin personal-channel risk consent ingress.

Never accepts actor identity, session, policy plan, or connection owner claims
from HTTP input. No QR, linked device, or provider session is created here.
"""
from __future__ import annotations

import logging
from typing import Literal, TypeVar
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError, field_validator, model_validator

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.channels.host import ChannelHostServices
from ai_karen_engine.persistence.repositories.channel_repository import (
    ChannelRetirementConflict,
)
from ai_karen_engine.services.channels.consent_recovery import (
    PersonalConsentRecoveryService,
    RETIREMENT_MANDATORY_VERIFICATION_BLOCKERS,
    assess_retirement_evidence_snapshot,
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
    """Historical provider claims only; no live session or QR verifier exists."""

    model_config = ConfigDict(extra="forbid")

    availability: Literal["configured", "unavailable"]
    last_observed_phase: Literal[
        "ready", "qr_available", "connected",
        "disconnect_pending", "disconnected", "unknown",
    ] | None = None
    live_connected: StrictBool = False
    qr_available: StrictBool = False
    provider_unlinked: StrictBool = False

    @model_validator(mode="after")
    def require_honest_personal_provider_status(self) -> "PersonalPairingStatus":
        # This contract currently has no live native provider health or QR
        # retrieval capability. Persisted callbacks must never assert either.
        if self.live_connected or self.qr_available:
            raise ValueError("Live personal provider status is not independently available")
        if self.provider_unlinked and (
            self.availability != "configured"
            or self.last_observed_phase != "disconnected"
        ):
            raise ValueError("Provider unlink claim does not match persisted state")
        return self


class PersonalChannelInventoryItem(PersonalPairingStatus):
    connection_id: str
    installation_id: str
    provider_id: str | None = None
    active_consent_provider_ids: list[str]


class PersonalChannelInventoryResponse(BaseModel):
    connections: list[PersonalChannelInventoryItem]


_PersonalStatusModel = TypeVar("_PersonalStatusModel", bound=BaseModel)


def _validate_personal_status_projection(
    model: type[_PersonalStatusModel], payload: object,
) -> _PersonalStatusModel:
    """Fail closed on contradictory host claims, with a redacted API error."""
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        logger.error(
            "channel.personal_status.projection_invalid",
            extra={"error_type": type(exc).__name__, "schema": model.__name__},
        )
        raise HTTPException(503, "Personal channel status unavailable") from None


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
    return _validate_personal_status_projection(
        PersonalChannelInventoryResponse, {"connections": connections},
    )


class TelegramWebhookInspectionResponse(BaseModel):
    """Provider-reported observations only, never a connected status."""

    model_config = ConfigDict(extra="forbid")

    registered: StrictBool
    path_matches: StrictBool
    pending_update_count: StrictInt = Field(ge=0, le=1_000_000)
    provider_reported_error: StrictBool
    endpoint_origin_verified: Literal[False]

    @model_validator(mode="after")
    def require_consistent_provider_observations(self) -> "TelegramWebhookInspectionResponse":
        if not self.registered and self.path_matches:
            raise ValueError("Unregistered webhook cannot match tenant route")
        return self


@router.get(
    "/connections/{connection_id}/telegram-webhook",
    response_model=TelegramWebhookInspectionResponse,
)
async def inspect_telegram_webhook(
    connection_id: UUID,
    request: Request,
    user: UserData = Depends(get_current_user),
) -> TelegramWebhookInspectionResponse:
    """Operator-only, session-scoped inspection; no caller-supplied authority.

    The host and RuntimePolicy retain sole authority for the read-only
    provider request. Missing, foreign, disabled or non-Telegram connections
    share the same denied response to avoid resource enumeration.
    """
    host, tenant_id, user_id = _host_and_actor(request, user)
    try:
        connection = await host.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=str(connection_id),
        )
        if (
            connection is None
            or connection.tenant_id != tenant_id
            or connection.connection_id != str(connection_id)
            or connection.installation_id != "telegram-bot"
        ):
            raise PermissionError("Telegram connection inspection denied")
        session_id = str(uuid4())
        plan = await host.activation.issue_action_plan(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.inspect",
        )
        observation = await host.inspect_channel_webhook(
            tenant_id=tenant_id, connection_id=str(connection_id),
            user_id=user_id, session_id=session_id, authorized_plan=plan,
        )
    except PermissionError:
        raise HTTPException(403, "Telegram webhook inspection denied") from None
    except Exception as exc:
        logger.error(
            "channel.telegram_webhook.inspection_unavailable",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(503, "Telegram webhook inspection unavailable") from None
    return _validate_personal_status_projection(
        TelegramWebhookInspectionResponse, observation,
    )


class TelegramProvisionRequest(BaseModel):
    """Operator supplies Vault reference only; never a raw Telegram bot token."""

    model_config = ConfigDict(extra="forbid")

    provider_account_id: str = Field(min_length=1, max_length=256)
    credential_handle: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def require_vault_reference(self) -> "TelegramProvisionRequest":
        # The Vault resolver validates actual permissions and secret types.
        # Refuse obviously raw tokens before invoking any authorization or SQL.
        if (
            not self.provider_account_id.strip()
            or self.provider_account_id != self.provider_account_id.strip()
            or not self.credential_handle.startswith("vault://")
        ):
            raise ValueError("Valid provider identity and Vault reference required")
        try:
            handle_id = UUID(self.credential_handle[len("vault://"):])
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Canonical Vault credential reference required") from None
        if self.credential_handle != "vault://" + str(handle_id):
            raise ValueError("Canonical Vault credential reference required")
        return self


class TelegramProvisionResult(BaseModel):
    """No credential handle, provider identity, secrets or live health claim."""

    model_config = ConfigDict(extra="forbid")

    connection_id: UUID
    installation_id: Literal["telegram-bot"]
    enabled: Literal[False]
    revision: Literal[1]
    operational: Literal[False]


@router.post(
    "/operator/telegram/connections",
    status_code=201,
    response_model=TelegramProvisionResult,
)
async def provision_telegram_connection(
    payload: TelegramProvisionRequest,
    request: Request,
    user: UserData = Depends(get_current_user),
) -> TelegramProvisionResult:
    """Create only a disabled Telegram connection after canonical authorization.

    This route does not accept caller identity, tenant, installation, policy
    plan or an activation flag. The separate activation and linking owners
    must still verify provider identity, signed delivery and ChatRuntime.
    """
    host, tenant_id, user_id = _host_and_actor(request, user)
    try:
        session_id = str(uuid4())
        plan = await host.activation.issue_action_plan(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id="telegram-bot", action="channel.provision",
        )
        result = await host.activation.provision(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id="telegram-bot",
            provider_account_id=payload.provider_account_id,
            credential_handle=payload.credential_handle,
            authorized_plan=plan,
        )
    except PermissionError:
        raise HTTPException(403, "Telegram provisioning denied") from None
    except Exception as exc:
        logger.error(
            "channel.telegram.provision_unavailable",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(503, "Telegram provisioning unavailable") from None
    try:
        if (
            result.tenant_id != tenant_id
            or result.installation_id != "telegram-bot"
            or result.enabled is not False
            or result.revision != 1
        ):
            raise ValueError("Invalid provisioned connection")
        return TelegramProvisionResult(
            connection_id=UUID(result.connection_id),
            installation_id="telegram-bot",
            enabled=False, revision=1, operational=False,
        )
    except (ValueError, ValidationError, AttributeError, TypeError):
        logger.error("channel.telegram.provision_result_invalid")
        raise HTTPException(503, "Telegram provisioning unavailable") from None


class TelegramActivationRequest(BaseModel):
    """Optimistic source revision only, never a caller-defined provider plan."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: StrictInt = Field(ge=1)


class TelegramActivationResult(BaseModel):
    """Locally activated, not a provider-webhook or conversation claim."""

    model_config = ConfigDict(extra="forbid")

    connection_id: UUID
    installation_id: Literal["telegram-bot"]
    enabled: Literal[True]
    revision: StrictInt = Field(ge=2)
    provider_identity_verified_at_activation: Literal[True]
    webhook_registration_verified: Literal[False]
    live_connected: Literal[False]


@router.post(
    "/operator/telegram/connections/{connection_id}/activate",
    response_model=TelegramActivationResult,
)
async def activate_telegram_connection(
    connection_id: UUID,
    payload: TelegramActivationRequest,
    request: Request,
    user: UserData = Depends(get_current_user),
) -> TelegramActivationResult:
    """Delegate activation to ChannelHost with a fresh one-action policy plan."""
    host, tenant_id, user_id = _host_and_actor(request, user)
    try:
        connection = await host.repository.get_connection(
            tenant_id=tenant_id, connection_id=str(connection_id),
        )
        if (
            connection is None
            or connection.tenant_id != tenant_id
            or connection.connection_id != str(connection_id)
            or connection.installation_id != "telegram-bot"
            or connection.enabled
            or connection.revision != payload.expected_revision
        ):
            raise PermissionError("Telegram activation denied")
        session_id = str(uuid4())
        plan = await host.activation.issue_action_plan(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.activate",
        )
        result = await host.activate_telegram_connection(
            tenant_id=tenant_id, connection_id=str(connection_id),
            user_id=user_id, session_id=session_id,
            authorized_plan=plan, expected_revision=payload.expected_revision,
        )
    except PermissionError:
        raise HTTPException(403, "Telegram activation denied") from None
    except Exception as exc:
        logger.error(
            "channel.telegram.activation_unavailable",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(503, "Telegram activation unavailable") from None
    try:
        if (
            result.tenant_id != tenant_id
            or result.connection_id != str(connection_id)
            or result.installation_id != "telegram-bot"
            or result.enabled is not True
            or result.revision != payload.expected_revision + 1
        ):
            raise ValueError("Invalid activation result")
        return TelegramActivationResult(
            connection_id=connection_id, installation_id="telegram-bot",
            enabled=True, revision=result.revision,
            provider_identity_verified_at_activation=True,
            webhook_registration_verified=False, live_connected=False,
        )
    except (ValueError, ValidationError, AttributeError, TypeError):
        logger.error("channel.telegram.activation_result_invalid")
        raise HTTPException(503, "Telegram activation unavailable") from None


class TelegramWebhookRegistrationRequest(BaseModel):
    """No URL, secret or provider-selected installation may enter from HTTP."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: StrictInt = Field(ge=1)


class TelegramWebhookRegistrationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_registration_verified: Literal[True]
    live_connected: Literal[False]


@router.post(
    "/operator/telegram/connections/{connection_id}/webhook",
    response_model=TelegramWebhookRegistrationResult,
)
async def register_telegram_webhook(
    connection_id: UUID,
    payload: TelegramWebhookRegistrationRequest,
    request: Request,
    user: UserData = Depends(get_current_user),
) -> TelegramWebhookRegistrationResult:
    """Explicitly register only the trusted configured webhook destination."""
    host, tenant_id, user_id = _host_and_actor(request, user)
    try:
        connection = await host.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=str(connection_id),
        )
        if (
            connection is None
            or connection.tenant_id != tenant_id
            or connection.connection_id != str(connection_id)
            or connection.installation_id != "telegram-bot"
            or connection.revision != payload.expected_revision
        ):
            raise PermissionError("Telegram webhook connection unavailable")
        session_id = str(uuid4())
        plan = await host.activation.issue_action_plan(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.webhook.register",
        )
        result = await host.register_telegram_webhook(
            tenant_id=tenant_id, connection_id=str(connection_id),
            user_id=user_id, session_id=session_id,
            authorized_plan=plan, expected_revision=payload.expected_revision,
        )
    except PermissionError:
        raise HTTPException(403, "Telegram webhook registration denied or unverified") from None
    except Exception as exc:
        logger.error(
            "channel.telegram.webhook.registration_unavailable",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(503, "Telegram webhook registration unavailable") from None
    try:
        return TelegramWebhookRegistrationResult.model_validate(result)
    except ValidationError:
        logger.error("channel.telegram.webhook.registration_result_invalid")
        raise HTTPException(503, "Telegram webhook registration unverified") from None


class TelegramReconciliationObservation(BaseModel):
    """Read-only evidence; cannot unlock a provider mutation."""

    model_config = ConfigDict(extra="forbid")

    claim_state: Literal["absent", "in_flight", "uncertain", "verified"]
    claim_revision_matches: StrictBool
    claim_expired: StrictBool
    provider_url_matches: StrictBool
    provider_webhook_registered: StrictBool
    live_connected: Literal[False]
    claim_released: Literal[False]
    reconciliation_authorized: Literal[False]


@router.get(
    "/operator/telegram/connections/{connection_id}/reconciliation",
    response_model=TelegramReconciliationObservation,
)
async def inspect_telegram_registration_reconciliation(
    connection_id: UUID,
    expected_revision: int,
    request: Request,
    user: UserData = Depends(get_current_user),
) -> TelegramReconciliationObservation:
    """Require fresh operator policy, never mutate remote webhook or SQL claims."""
    if type(expected_revision) is not int or expected_revision < 1:
        raise HTTPException(422, "Positive revision required")
    host, tenant_id, user_id = _host_and_actor(request, user)
    try:
        connection = await host.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=str(connection_id),
        )
        if (
            connection is None
            or connection.tenant_id != tenant_id
            or connection.connection_id != str(connection_id)
            or connection.installation_id != "telegram-bot"
            or connection.revision != expected_revision
        ):
            raise PermissionError("Telegram reconciliation unavailable")
        session_id = str(uuid4())
        plan = await host.activation.issue_action_plan(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id="telegram-bot", action="channel.inspect",
        )
        result = await host.inspect_telegram_registration_evidence(
            tenant_id=tenant_id, connection_id=str(connection_id),
            user_id=user_id, session_id=session_id,
            authorized_plan=plan, expected_revision=expected_revision,
        )
    except PermissionError:
        raise HTTPException(403, "Telegram reconciliation inspection denied") from None
    except Exception as exc:
        logger.error(
            "channel.telegram.reconciliation.unavailable",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(503, "Telegram reconciliation inspection unavailable") from None
    try:
        return TelegramReconciliationObservation.model_validate(result)
    except ValidationError:
        logger.error("channel.telegram.reconciliation.invalid_projection")
        raise HTTPException(503, "Telegram reconciliation inspection unavailable") from None


class PersonalConsentRecoveryItem(BaseModel):
    connection_id: str
    provider_id: str
    policy_version: str


class PersonalConsentRecoveryInventory(BaseModel):
    consents: list[PersonalConsentRecoveryItem]


class PersonalRetirementAssessment(BaseModel):
    """Version-fenced blocker report, never a cleanup authorization grant."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["retirement-verification-readiness-v2"]
    status: Literal["blocked"]
    cleanup_authorized: Literal[False]
    provider_unlink_independently_verified: Literal[False]
    credential_erasure_independently_verified: Literal[False]
    retention_scope_verified: Literal[False]
    blocking_reasons: list[Literal[
        "local_retirement_hold_missing",
        "local_connection_still_enabled",
        "active_pairing_consent_remains",
        "pairing_teardown_unresolved",
        "provider_unlink_claim_missing",
        "credential_deletion_request_missing",
        "credential_deletion_claim_missing",
        "provider_revision_claims_mismatched",
        "credential_deletion_requests_unverified",
        "inbound_work_unresolved",
        "outbound_delivery_unconfirmed",
        "provider_unlink_independent_verification_unavailable",
        "credential_erasure_independent_verification_unavailable",
        "retention_and_backup_scope_verification_unavailable",
        "governed_final_cleanup_authority_unavailable",
    ]] = Field(min_length=4)

    @field_validator("blocking_reasons")
    @classmethod
    def require_independent_verification_blockers(cls, codes: list[str]) -> list[str]:
        # The existing verification owner defines what cannot currently be
        # attested. Pydantic must not accept a mocked/incomplete backend
        # that silently removes one of those mandatory blockers.
        if len(set(codes)) != len(codes) or not all(
            code in codes for code in RETIREMENT_MANDATORY_VERIFICATION_BLOCKERS
        ):
            raise ValueError("Independent retirement verification evidence unavailable")
        return codes


class PersonalRetirementEvidenceItem(BaseModel):
    """Backend facts and derived blockers must describe the same snapshot."""

    model_config = ConfigDict(extra="forbid")

    connection_id: str = Field(min_length=1, max_length=256)
    connection_revision: StrictInt = Field(gt=0)
    connection_enabled: StrictBool
    retirement_held: StrictBool
    active_consent: StrictBool
    unresolved_pairing: StrictBool
    provider_unlink_claim_recorded: StrictBool
    deletion_request_recorded: StrictBool
    credential_deletion_claim_recorded: StrictBool
    provider_revision_claims_correlated: StrictBool
    unverified_deletion_request: StrictBool
    inbox_not_completed: StrictBool
    outbound_not_confirmed: StrictBool
    retirement_assessment: PersonalRetirementAssessment

    @model_validator(mode="after")
    def require_consistent_retirement_assessment(self) -> "PersonalRetirementEvidenceItem":
        # Reuse the canonical assessment owner. A mocked, stale or malformed
        # service response cannot detach blockers from the SQL facts. The
        # existing API never grants cleanup or invents independent verification.
        facts = self.model_dump(exclude={"retirement_assessment"})
        expected = assess_retirement_evidence_snapshot(facts)
        if expected["retirement_assessment"] != self.retirement_assessment.model_dump():
            raise ValueError("Retirement assessment does not match stored evidence")
        return self


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
        return PersonalRetirementEvidenceInventory(connections=rows)
    except PermissionError as exc:
        raise _translate(exc, operation="recovery") from None
    except Exception as exc:
        # This GET accepts no user data beyond an authenticated principal.
        # Missing, malformed or forged backend evidence is a server integrity
        # failure, not a recoverable client validation problem.
        logger.error(
            "channel.personal_retirement.evidence_invalid",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(
            503, "Personal channel retirement evidence unavailable",
        ) from None


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
    return _validate_personal_status_projection(PersonalPairingStatus, result)


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
