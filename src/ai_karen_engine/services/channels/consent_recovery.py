"""Transport-independent revocation of persisted personal-channel consent.

This is the retired-installation lifecycle of the canonical channel consent
ledger, NOT another ChannelHost or a pairing/activation service. It exists so
a person can withdraw stored consent even when no adapter is registered.
All eligibility derives from fresh tenant identity, central RBAC, RuntimePolicy
and the same tenant-RLS SqlChannelRepository used by ChannelHost.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
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


__all__ = ["PersonalConsentRecoveryService"]
