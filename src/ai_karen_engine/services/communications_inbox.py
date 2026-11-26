"""Governed self-service communications lifecycle; no runtime side effects."""
from __future__ import annotations

import logging
from uuid import UUID

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager
from ai_karen_engine.core.security.auth_config import auth_config
from ai_karen_engine.persistence.repositories.communications_inbox_repository import (
    CommunicationsInboxRepository,
    InboxCursor,
    InboxFilter,
    InboxMutation,
    InboxOperation,
    InboxPage,
)
from ai_karen_engine.services.audit.audit_logging import (
    AuditEvent,
    AuditEventType,
    AuditSeverity,
    get_audit_logger,
)

logger = logging.getLogger(__name__)


class CommunicationsAuthorizationError(PermissionError):
    """An active, verified principal with explicit inbox permission is required."""


class CommunicationsInboxService:
    def __init__(self, repository: CommunicationsInboxRepository | None = None) -> None:
        self._repository = repository if repository is not None else CommunicationsInboxRepository()

    @staticmethod
    def _authorize(
        user: UserData, permission: Permission, correlation_id: str,
    ) -> tuple[str, str]:
        if (
            auth_config.should_bypass_auth()
            or not isinstance(user, UserData)
            or user.is_active is not True
            or user.is_verified is not True
        ):
            raise CommunicationsAuthorizationError("Verified communications principal required")
        try:
            tenant_id = str(UUID(str(user.tenant_id)))
            user_id = str(UUID(str(user.user_id)))
        except (ValueError, TypeError, AttributeError):
            raise CommunicationsAuthorizationError("Verified communications principal required") from None
        allowed = get_rbac_manager().has_permission(user, permission)
        get_audit_logger().log_audit_event(AuditEvent(
            event_type=AuditEventType.ACCESS_GRANTED if allowed else AuditEventType.ACCESS_DENIED,
            severity=AuditSeverity.INFO if allowed else AuditSeverity.WARNING,
            message="communications_inbox_permission_check",
            user_id=user_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            metadata={"permission": permission.value, "resource": "communications_inbox"},
        ))
        if not allowed:
            raise CommunicationsAuthorizationError("Communications permission denied")
        return tenant_id, user_id

    async def list_owned(
        self, *, user: UserData, correlation_id: str, limit: int,
        inbox_filter: InboxFilter, cursor: InboxCursor | None,
    ) -> InboxPage:
        tenant_id, user_id = self._authorize(user, Permission.COMMUNICATIONS_READ, correlation_id)
        return await self._repository.list_entries(
            tenant_id=tenant_id, user_id=user_id, limit=limit,
            inbox_filter=inbox_filter, cursor=cursor,
        )

    async def mutate_owned(
        self, *, user: UserData, correlation_id: str, entry_id: UUID,
        operation: InboxOperation, expected_revision: int,
    ) -> InboxMutation:
        # Mutations return private readback, so both entitlements are necessary.
        self._authorize(user, Permission.COMMUNICATIONS_READ, correlation_id)
        tenant_id, user_id = self._authorize(user, Permission.COMMUNICATIONS_WRITE, correlation_id)
        result = await self._repository.mutate(
            tenant_id=tenant_id, user_id=user_id, entry_id=str(entry_id),
            operation=operation, expected_revision=expected_revision,
        )
        # Repository exits its transaction before reporting the outcome.
        logger.info("communications.inbox.lifecycle_committed", extra={
            "tenant_id": tenant_id, "user_id": user_id,
            "correlation_id": correlation_id, "entry_id": str(entry_id),
            "operation": operation.value, "revision": result.entry.revision,
            "changed": result.changed,
        })
        return result
