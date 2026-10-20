"""Single governed service boundary for personal-planner operations.

HTTP ingress and ChatRuntime may call this service only with authenticated
UserData. It delegates durable writes to the canonical repository. It never
executes tasks, creates memory, or permits caller-supplied ownership scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager
from ai_karen_engine.services.audit.audit_logging import AuditEvent, AuditEventType, AuditSeverity, get_audit_logger
from ai_karen_engine.core.planner.contracts import (
    CommitmentMutation,
    PersonalCommitment,
    PersistedCommitmentReceipt,
)
from ai_karen_engine.persistence.repositories.personal_planner_repository import (
    PersonalPlannerRepository,
)


class PlannerAuthorizationError(PermissionError):
    """An authenticated, active principal with valid tenant scope is required."""


@dataclass(frozen=True)
class PlannerPrincipal:
    tenant_id: UUID
    owner_id: UUID

    @classmethod
    def from_authenticated_user(cls, user: UserData) -> "PlannerPrincipal":
        if not user or not user.is_active:
            raise PlannerAuthorizationError("Active authenticated user required")
        if str(user.tenant_id or "").strip() in ("", "default"):
            raise PlannerAuthorizationError("Verified tenant identity required")
        try:
            tenant_id = UUID(str(user.tenant_id))
            owner_id = UUID(str(user.user_id))
        except (TypeError, ValueError) as exc:
            raise PlannerAuthorizationError("Valid tenant and user identities required") from exc
        return cls(tenant_id=tenant_id, owner_id=owner_id)


def _authorize(user: UserData, permission: Permission, *, correlation_id: str | None = None) -> None:
    allowed = get_rbac_manager().has_permission(user, permission)
    get_audit_logger().log_audit_event(AuditEvent(
        event_type=AuditEventType.ACCESS_GRANTED if allowed else AuditEventType.ACCESS_DENIED,
        severity=AuditSeverity.INFO if allowed else AuditSeverity.WARNING,
        message="personal_planner_permission_check",
        user_id=str(user.user_id),
        tenant_id=str(user.tenant_id),
        correlation_id=correlation_id,
        metadata={"permission": permission.value, "resource": "personal_planner"},
    ))
    if not allowed:
        raise PlannerAuthorizationError("Planner permission denied")


class PersonalPlannerService:
    def __init__(self, repository: PersonalPlannerRepository | None = None) -> None:
        self._repository = repository if repository is not None else PersonalPlannerRepository()

    async def get(self, *, user: UserData, commitment_id: UUID) -> PersonalCommitment:
        identity = PlannerPrincipal.from_authenticated_user(user)
        _authorize(user, Permission.DATA_READ)
        return await self._repository.get(
            tenant_id=identity.tenant_id,
            owner_id=identity.owner_id,
            commitment_id=commitment_id,
        )

    async def create(
        self, *, user: UserData, title: str, timezone: str,
        idempotency_key: UUID, correlation_id: str,
    ) -> tuple[PersonalCommitment, PersistedCommitmentReceipt]:
        identity = PlannerPrincipal.from_authenticated_user(user)
        _authorize(user, Permission.DATA_WRITE, correlation_id=correlation_id)
        if not correlation_id or len(correlation_id) > 128:
            raise ValueError("Correlation ID required")
        return await self._repository.create(
            tenant_id=identity.tenant_id,
            owner_id=identity.owner_id,
            title=title, timezone=timezone,
            idempotency_key=idempotency_key, correlation_id=correlation_id,
        )

    async def update(
        self, *, user: UserData, commitment_id: UUID,
        mutation: CommitmentMutation, correlation_id: str,
    ) -> PersonalCommitment:
        identity = PlannerPrincipal.from_authenticated_user(user)
        if not correlation_id or len(correlation_id) > 128:
            raise ValueError("Correlation ID required")
        return await self._repository.update(
            tenant_id=identity.tenant_id,
            owner_id=identity.owner_id,
            commitment_id=commitment_id, mutation=mutation,
            correlation_id=correlation_id,
        )
