"""Governed self-service communications lifecycle; no runtime side effects."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from ai_karen_engine.config.runtime import get_runtime_settings
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager
from ai_karen_engine.core.security.auth_config import auth_config
from ai_karen_engine.core.realtime.inbox_invalidation import (
    InboxInvalidationUnavailable, wait_for_inbox_invalidation,
)
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


class CommunicationsProducerUnavailable(RuntimeError):
    """Terminal projection has not been activated."""


@dataclass(frozen=True, slots=True)
class InboxCapabilities:
    """Server-authoritative entitlements and configuration, not health proof."""

    can_mutate: bool
    producer_enabled: bool
    can_reconcile: bool
    invalidation_wait_enabled: bool = False


@dataclass(frozen=True, slots=True)
class OwnedInboxPage:
    page: InboxPage
    capabilities: InboxCapabilities


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
    ) -> OwnedInboxPage:
        tenant_id, user_id = self._authorize(user, Permission.COMMUNICATIONS_READ, correlation_id)
        page = await self._repository.list_entries(
            tenant_id=tenant_id, user_id=user_id, limit=limit,
            inbox_filter=inbox_filter, cursor=cursor,
        )
        # These are UI affordances only. Every mutation reauthorizes the
        # current principal; a previously returned capability is not a grant.
        can_mutate = get_rbac_manager().has_permission(user, Permission.COMMUNICATIONS_WRITE)
        features = get_runtime_settings().features
        producer_enabled = features.enable_communications_terminal_producer
        return OwnedInboxPage(page, InboxCapabilities(
            can_mutate=can_mutate, producer_enabled=producer_enabled,
            can_reconcile=can_mutate and producer_enabled,
            invalidation_wait_enabled=(
                features.enable_communications_invalidation is True
                and features.enable_communications_invalidation_wait is True
            ),
        ))

    async def wait_owned(
        self, *, user: UserData, correlation_id: str,
        reauthenticate: Callable[[], Awaitable[UserData]],
        disconnected: Callable[[], Awaitable[bool]],
    ) -> bool:
        """Admit only the current owner; reauthorize after releasing Redis."""
        scope = self._authorize(user, Permission.COMMUNICATIONS_READ, correlation_id)
        changed = await wait_for_inbox_invalidation(
            tenant_id=scope[0], user_id=scope[1], disconnected=disconnected,
        )
        fresh = await reauthenticate()
        if self._authorize(fresh, Permission.COMMUNICATIONS_READ, correlation_id) != scope:
            raise CommunicationsAuthorizationError("Communications principal changed")
        if await disconnected():
            raise InboxInvalidationUnavailable("Communications invalidation unavailable")
        settings = get_runtime_settings()
        if (
            settings.features.enable_communications_invalidation is not True
            or settings.features.enable_communications_invalidation_wait is not True
        ):
            raise InboxInvalidationUnavailable("Communications invalidation unavailable")
        logger.info("communications.invalidation.wait_completed", extra={
            "tenant_id": scope[0], "user_id": scope[1],
            "correlation_id": correlation_id, "changed": changed,
        })
        return changed

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

    async def reconcile_owned(self, *, user: UserData, correlation_id: str) -> int:
        """Explicit owner-scoped recovery, not arbitrary notification creation."""
        self._authorize(user, Permission.COMMUNICATIONS_READ, correlation_id)
        tenant_id, user_id = self._authorize(user, Permission.COMMUNICATIONS_WRITE, correlation_id)
        if not get_runtime_settings().features.enable_communications_terminal_producer:
            raise CommunicationsProducerUnavailable("Communications producer unavailable")
        count = await self._repository.reconcile_pending(tenant_id=tenant_id, user_id=user_id)
        logger.info("communications.inbox.reconciliation_committed", extra={
            "tenant_id": tenant_id, "user_id": user_id,
            "correlation_id": correlation_id, "admitted_count": count,
        })
        return count
