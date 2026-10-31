"""Canonical authenticated countdown lifecycle over PostgreSQL automation state.

A persisted timer deadline does not promise notification delivery. All writes
and reads require the current principal and are separately audited.
"""

from __future__ import annotations

import uuid
from typing import Any

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.rbac_middleware import (
    Permission,
    get_rbac_manager,
)
from ai_karen_engine.persistence.repositories.automation_repository import (
    SqlAutomationRepository,
    get_automation_repository,
)
from ai_karen_engine.services.audit.audit_logging import (
    AuditEvent,
    AuditEventType,
    AuditSeverity,
    get_audit_logger,
)


class TimerAuthorizationError(PermissionError):
    """The principal has no rights to read or mutate owned timers."""


class TimerNotFoundError(LookupError):
    """The timer does not exist within the authenticated tenant and owner."""


class OwnedTimerService:
    def __init__(self, repository: SqlAutomationRepository | None = None) -> None:
        self._repository = repository or get_automation_repository()

    @staticmethod
    def _principal(user: UserData, permission: Permission, correlation_id: str) -> tuple[str, str]:
        if user is None or user.is_active is not True:
            raise TimerAuthorizationError("Active authenticated principal required")
        try:
            tenant = str(uuid.UUID(str(user.tenant_id)))
            owner = str(uuid.UUID(str(user.user_id)))
        except (TypeError, ValueError, AttributeError) as exc:
            raise TimerAuthorizationError("Verified tenant and principal required") from exc
        allowed = get_rbac_manager().has_permission(user, permission)
        get_audit_logger().log_audit_event(AuditEvent(
            event_type=AuditEventType.ACCESS_GRANTED if allowed else AuditEventType.ACCESS_DENIED,
            severity=AuditSeverity.INFO if allowed else AuditSeverity.WARNING,
            message="owned_timer_permission_check",
            user_id=owner,
            tenant_id=tenant,
            correlation_id=correlation_id,
            metadata={"permission": permission.value, "resource": "automation_timer"},
        ))
        if not allowed:
            raise TimerAuthorizationError("Timer permission denied")
        return tenant, owner

    async def create(
        self,
        *,
        user: UserData,
        duration_seconds: int,
        title: str,
        idempotency_key: uuid.UUID,
        correlation_id: str,
    ) -> dict[str, Any]:
        tenant, owner = self._principal(user, Permission.TIMER_WRITE, correlation_id)
        return await self._repository.create_owned_timer(
            tenant_id=tenant, owner_id=owner,
            duration_seconds=duration_seconds,
            title=title, idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    async def get(
        self, *, user: UserData, timer_id: uuid.UUID, correlation_id: str,
    ) -> dict[str, Any]:
        tenant, owner = self._principal(user, Permission.TIMER_READ, correlation_id)
        record = await self._repository.get_owned_timer(
            tenant_id=tenant, owner_id=owner, timer_id=timer_id,
        )
        if record is None:
            raise TimerNotFoundError("Timer not found")
        return record

    async def list(
        self, *, user: UserData, correlation_id: str, limit: int = 20,
    ) -> list[dict[str, Any]]:
        tenant, owner = self._principal(user, Permission.TIMER_READ, correlation_id)
        return await self._repository.list_owned_timers(
            tenant_id=tenant, owner_id=owner, limit=limit,
        )

    async def cancel(
        self, *, user: UserData, timer_id: uuid.UUID, correlation_id: str,
    ) -> dict[str, Any]:
        tenant, owner = self._principal(user, Permission.TIMER_WRITE, correlation_id)
        record = await self._repository.cancel_owned_timer(
            tenant_id=tenant, owner_id=owner, timer_id=timer_id,
        )
        if record is None:
            raise TimerNotFoundError("Timer not found")
        return record
