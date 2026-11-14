"""Transport-independent revocation of persisted personal-channel consent.

This is the retired-installation lifecycle of the canonical channel consent
ledger, NOT another ChannelHost or a pairing/activation service. It exists so
a person can withdraw stored consent even when no adapter is registered.
All eligibility derives from fresh tenant identity, central RBAC, RuntimePolicy
and the same tenant-RLS SqlChannelRepository used by ChannelHost.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from uuid import UUID, uuid4

from ai_karen_engine.auth.auth_service import get_auth_service
from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager
from ai_karen_engine.core.runtime.contracts import ActionExecutionGate
from ai_karen_engine.core.runtime.policy.runtime_policy import (
    PolicyEvaluationRequest,
    RuntimePolicyEnforcer,
)
from ai_karen_engine.persistence.repositories.channel_repository import (
    SqlChannelRepository,
)
from ai_karen_engine.services.auth.auth_service import UserStatus
from ai_karen_engine.services.auth.fresh_user_lookup import get_fresh_user_by_id

logger = logging.getLogger(__name__)

RETIREMENT_VERIFICATION_CONTRACT_VERSION = "retirement-verification-readiness-v2"

_RETIREMENT_BOOLEAN_FIELDS = (
    "connection_enabled",
    "retirement_held",
    "active_consent",
    "unresolved_pairing",
    "provider_unlink_claim_recorded",
    "deletion_request_recorded",
    "credential_deletion_claim_recorded",
    "provider_revision_claims_correlated",
    "unverified_deletion_request",
    "inbox_not_completed",
    "outbound_not_confirmed",
)

RETIREMENT_MANDATORY_VERIFICATION_BLOCKERS = (
    "provider_unlink_independent_verification_unavailable",
    "credential_erasure_independent_verification_unavailable",
    "retention_and_backup_scope_verification_unavailable",
    "governed_final_cleanup_authority_unavailable",
)


def assess_retirement_evidence_snapshot(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Explain local and remote retirement blockers without minting authority.

    This is not an erasure verifier or permission grant. Verified status in
    historical vendor records is NOT independent source-authenticated proof;
    until a separately governed verifier and retention evidence exist, all
    cleanup remains unavailable. Strict typing prevents malformed SQL or
    test adapters from masquerading as a safe snapshot.
    """
    if (
        not isinstance(record, Mapping)
        or not isinstance(record.get("connection_id"), str)
        or not 1 <= len(record["connection_id"].strip()) <= 256
        or type(record.get("connection_revision")) is not int
        or record["connection_revision"] < 1
        or any(type(record.get(field)) is not bool for field in _RETIREMENT_BOOLEAN_FIELDS)
    ):
        raise ValueError("Retirement assessment requires complete stored evidence")
    # This is a provider/revision match only. Pairing evidence has no canonical
    # remote session identifier, and neither claim is independently attested.
    # Reject an impossible SQL snapshot rather than exposing a coherent state.
    if record["provider_revision_claims_correlated"] and not (
        record["retirement_held"]
        and not record["connection_enabled"]
        and record["provider_unlink_claim_recorded"]
        and record["credential_deletion_claim_recorded"]
    ):
        raise ValueError("Retirement claim correlation evidence inconsistent")

    blockers: list[str] = []
    def block_if(condition: bool, reason: str) -> None:
        if condition:
            blockers.append(reason)

    block_if(not record["retirement_held"], "local_retirement_hold_missing")
    block_if(record["connection_enabled"], "local_connection_still_enabled")
    block_if(record["active_consent"], "active_pairing_consent_remains")
    block_if(record["unresolved_pairing"], "pairing_teardown_unresolved")
    block_if(
        not record["provider_unlink_claim_recorded"],
        "provider_unlink_claim_missing",
    )
    block_if(
        not record["deletion_request_recorded"],
        "credential_deletion_request_missing",
    )
    block_if(
        not record["credential_deletion_claim_recorded"],
        "credential_deletion_claim_missing",
    )
    block_if(
        record["provider_unlink_claim_recorded"]
        and record["credential_deletion_claim_recorded"]
        and not record["provider_revision_claims_correlated"],
        "provider_revision_claims_mismatched",
    )
    block_if(
        record["unverified_deletion_request"],
        "credential_deletion_requests_unverified",
    )
    block_if(record["inbox_not_completed"], "inbound_work_unresolved")
    block_if(record["outbound_not_confirmed"], "outbound_delivery_unconfirmed")

    # These independent sources of authority do not yet exist. In particular,
    # a forged historical 'verified' row cannot suppress these mandatory
    # blockers; claims and a quiet local queue are never sufficient.
    blockers.extend(RETIREMENT_MANDATORY_VERIFICATION_BLOCKERS)
    return {
        # Whitelist the original owner-only SQL columns. An unexpected
        # repository adapter field must not expose session, credential,
        # vendor receipt or message data to a recovery caller.
        "connection_id": record["connection_id"],
        "connection_revision": record["connection_revision"],
        **{field: record[field] for field in _RETIREMENT_BOOLEAN_FIELDS},
        "retirement_assessment": {
            "contract_version": RETIREMENT_VERIFICATION_CONTRACT_VERSION,
            "status": "blocked",
            "cleanup_authorized": False,
            "provider_unlink_independently_verified": False,
            "credential_erasure_independently_verified": False,
            "retention_scope_verified": False,
            "blocking_reasons": blockers,
        },
    }


class PersonalConsentRecoveryService:
    """Read and revoke stored risk consent without requiring channel startup."""

    def __init__(
        self,
        *,
        repository: SqlChannelRepository | None = None,
        principal_lookup: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        self._repository = repository if repository is not None else SqlChannelRepository()
        self._principal_lookup = (
            principal_lookup if principal_lookup is not None else self._fresh_principal
        )

    @staticmethod
    async def _fresh_principal(*, tenant_id: str, user_id: str) -> Any:
        return await get_fresh_user_by_id(
            await get_auth_service(), tenant_id=tenant_id, user_id=user_id,
        )

    async def _authorize(self, *, tenant_id: str, user_id: str) -> tuple[str, str]:
        """Mint a new, plugin-independent channel.consent RuntimePolicy decision."""
        try:
            tenant_id = str(UUID(tenant_id))
            user_id = str(UUID(user_id))
        except (ValueError, TypeError, AttributeError):
            raise PermissionError("Durable consent recovery identity required") from None

        principal = await self._principal_lookup(
            tenant_id=tenant_id, user_id=user_id,
        )
        if (
            principal is None
            or getattr(principal, "status", None) is not UserStatus.ACTIVE
            or getattr(principal, "is_verified", None) is not True
            or str(getattr(principal, "tenant_id", "")) != tenant_id
            or str(getattr(principal, "id", "")) != user_id
        ):
            raise PermissionError("Active verified tenant principal required")

        roles = {
            str(getattr(role, "value", role))
            for role in (getattr(principal, "roles", None) or ())
        }
        granted = get_rbac_manager().get_user_permissions({
            "user_id": user_id,
            "tenant_id": tenant_id,
            "roles": sorted(roles),
            "permissions": [],
        })
        if Permission.CHANNEL_CONSENT not in granted:
            raise PermissionError("Channel consent recovery RBAC denied")

        session_id = str(uuid4())
        decision = await RuntimePolicyEnforcer().evaluate(PolicyEvaluationRequest(
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=session_id,
            roles=sorted(roles),
            permissions=sorted(permission.value for permission in granted),
            action="channel.consent",
            requested_capabilities=["channel.consent"],
            max_model_calls=0,
            # No plugin or extension identity: a removed installation cannot
            # authorize itself or prevent withdrawal from durable SQL.
        ))
        if not decision.allowed:
            raise PermissionError("Channel consent recovery RuntimePolicy denied")
        plan = decision.to_authorized_plan()
        if (
            not plan.matches_execution_scope(
                user_id=user_id, tenant_id=tenant_id, session_id=session_id,
            )
            or "channel.consent" not in plan.allowed_capabilities
            or plan.approval_requirements
            or not await ActionExecutionGate.authorize(plan, "channel.consent")
        ):
            raise PermissionError("Channel consent recovery action gate denied")

        logger.info(
            "channel.personal_consent.recovery_authorized",
            extra={
                "tenant_id": tenant_id,
                "user_id": user_id,
                "session_id": session_id,
                "action": "channel.consent",
                "policy_decision_id": plan.policy_decision_id,
            },
        )
        return tenant_id, user_id

    async def list_active(
        self, *, tenant_id: str, user_id: str,
    ) -> list[dict[str, str]]:
        """Return bounded active consent references owned by the caller."""
        tenant_id, user_id = await self._authorize(
            tenant_id=tenant_id, user_id=user_id,
        )
        return await self._repository.list_owned_active_personal_consents(
            tenant_id=tenant_id, user_id=user_id,
        )

    async def list_retirement_evidence(
        self, *, tenant_id: str, user_id: str,
    ) -> list[dict[str, Any]]:
        """Read bounded owner snapshots and fail-closed verification blockers."""
        tenant_id, user_id = await self._authorize(
            tenant_id=tenant_id, user_id=user_id,
        )
        rows = await self._repository.list_owned_personal_retirement_evidence(
            tenant_id=tenant_id, user_id=user_id,
        )
        if not isinstance(rows, list) or len(rows) > 50:
            raise ValueError("Personal retirement evidence inventory invalid")
        assessed = [assess_retirement_evidence_snapshot(row) for row in rows]
        if len({row["connection_id"] for row in assessed}) != len(assessed):
            raise ValueError("Duplicate connection retirement evidence")
        logger.info(
            "channel.personal_retirement.verification_assessment",
            extra={
                "tenant_id": tenant_id,
                "user_id": user_id,
                "record_count": len(assessed),
                "cleanup_authorized": False,
                "contract_version": RETIREMENT_VERIFICATION_CONTRACT_VERSION,
            },
        )
        return assessed

    async def list_deletion_requests(
        self, *, tenant_id: str, user_id: str,
    ) -> list[dict[str, str | int]]:
        """Read owner-only historical deletion requests without channel startup.

        A provider claim is not independent credential-erasure verification.
        The returned data is status metadata, not a deletion receipt.
        """
        tenant_id, user_id = await self._authorize(
            tenant_id=tenant_id, user_id=user_id,
        )
        return await self._repository.list_owned_personal_credential_deletion_requests(
            tenant_id=tenant_id, user_id=user_id,
        )

    async def revoke(
        self, *, tenant_id: str, user_id: str,
        connection_id: str, provider_id: str,
    ) -> bool:
        """Revoke only consent; never unlink the provider or alter a connection."""
        if (
            not isinstance(connection_id, str) or not connection_id.strip()
            or len(connection_id) > 128
            or not isinstance(provider_id, str) or not provider_id.strip()
            or len(provider_id) > 128
        ):
            raise ValueError("Invalid consent recovery resource scope")
        tenant_id, user_id = await self._authorize(
            tenant_id=tenant_id, user_id=user_id,
        )
        # The existing canonical repository transaction takes a connection-row
        # lock shared with pairing admission before revoking the exact owner's
        # consent. This also prevents a cross-tenant or unowned write.
        revoked = await self._repository.revoke_personal_pairing_consent(
            tenant_id=tenant_id,
            connection_id=connection_id,
            user_id=user_id,
            provider_id=provider_id,
        )
        logger.info(
            "channel.personal_consent.recovery_revocation",
            extra={
                "tenant_id": tenant_id,
                "user_id": user_id,
                "connection_id": connection_id,
                "provider_id": provider_id,
                "revoked": bool(revoked),
                "provider_unlinked": False,
            },
        )
        return revoked is True


__all__ = [
    "PersonalConsentRecoveryService",
    "RETIREMENT_VERIFICATION_CONTRACT_VERSION",
    "RETIREMENT_MANDATORY_VERIFICATION_BLOCKERS",
    "assess_retirement_evidence_snapshot",
]
