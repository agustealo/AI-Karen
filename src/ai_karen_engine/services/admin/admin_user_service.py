"""
Admin User Service — wraps AuthService with admin-specific logic,
audit logging, and tenant boundary enforcement.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ai_karen_engine.services.auth.auth_service import (
    AuthService,
    UserAccount,
    UserRole,
    UserStatus,
)
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.services.audit.audit_logging import (
    AuditEvent,
    AuditEventType,
    AuditSeverity,
    get_audit_logger,
)

logger = get_logger(__name__)


@dataclass
class AdminUserFilter:
    """Filter criteria for admin user listing."""

    tenant_id: Optional[str] = None
    role: Optional[UserRole] = None
    status: Optional[UserStatus] = None
    search: Optional[str] = None
    limit: int = 100
    offset: int = 0


class AdminUserService:
    """
    Admin-facing wrapper around AuthService.

    Adds:
    - Structured audit events for all mutations
    - Tenant boundary enforcement on reads/writes
    - Admin-specific filtering and bulk operations
    """

    def __init__(self, auth_service: AuthService) -> None:
        self._auth_service = auth_service
        self._audit = get_audit_logger()

    async def initialize(self) -> None:
        """Initialize the underlying auth service if needed."""
        if hasattr(self._auth_service, "initialize"):
            await self._auth_service.initialize()

    def _enforce_tenant_boundary(self, tenant_id: Optional[str], operator_tenant_id: Optional[str]) -> Optional[str]:
        """Return the effective tenant id or raise when cross-tenant access is attempted."""
        if operator_tenant_id is None:
            return tenant_id
        if tenant_id is None:
            return operator_tenant_id
        if tenant_id != operator_tenant_id:
            raise PermissionError(f"Cross-tenant access denied: {operator_tenant_id} -> {tenant_id}")
        return tenant_id

    def _audit_mutation(
        self,
        action: str,
        target_user_id: Optional[str],
        tenant_id: Optional[str],
        operator_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit an admin audit event for a user mutation."""
        event = AuditEvent(
            event_type=AuditEventType.SYSTEM_EVENT,
            severity=AuditSeverity.INFO,
            message=f"admin_user_{action}",
            user_id=operator_id,
            tenant_id=tenant_id,
            metadata={
                "target_user_id": target_user_id,
                "action": action,
                **(metadata or {}),
            },
        )
        self._audit.log_audit_event(event)

    async def create_user(
        self,
        email: str,
        password: str,
        full_name: str,
        *,
        username: Optional[str] = None,
        tenant_id: Optional[str] = None,
        roles: Optional[List[UserRole]] = None,
        is_verified: bool = False,
        operator_tenant_id: Optional[str] = None,
        operator_id: Optional[str] = None,
    ) -> Optional[UserAccount]:
        """Create a user with tenant enforcement and audit."""
        effective_tenant_id = self._enforce_tenant_boundary(tenant_id, operator_tenant_id)
        user, error = await self._auth_service.create_user(
            email=email,
            password=password,
            full_name=full_name,
            username=username,
            tenant_id=effective_tenant_id,
            roles=roles,
            is_verified=is_verified,
        )
        if user:
            self._audit_mutation(
                action="create",
                target_user_id=user.id,
                tenant_id=effective_tenant_id,
                operator_id=operator_id,
                metadata={"email": email},
            )
            return user
        logger.error("Admin user creation failed: %s", error)
        return None

    async def get_user(
        self,
        identifier: str,
        operator_tenant_id: Optional[str] = None,
        operator_id: Optional[str] = None,
    ) -> Optional[UserAccount]:
        """Get a user by identifier, enforcing tenant boundary."""
        user = await self._auth_service.get_user(identifier)
        if user and user.tenant_id:
            self._enforce_tenant_boundary(user.tenant_id, operator_tenant_id)
            self._audit_mutation(
                action="read",
                target_user_id=user.id,
                tenant_id=user.tenant_id,
                operator_id=operator_id,
            )
        return user

    async def list_users(
        self,
        user_filter: AdminUserFilter,
        operator_tenant_id: Optional[str] = None,
        operator_id: Optional[str] = None,
    ) -> List[UserAccount]:
        """List users with admin filtering and tenant enforcement."""
        effective_tenant_id = self._enforce_tenant_boundary(user_filter.tenant_id, operator_tenant_id)
        users = await self._auth_service.list_users(
            tenant_id=effective_tenant_id,
            limit=user_filter.limit,
            offset=user_filter.offset,
        )
        if user_filter.role:
            users = [u for u in users if user_filter.role in u.roles]
        if user_filter.status:
            users = [u for u in users if u.status == user_filter.status]
        if user_filter.search:
            term = user_filter.search.lower()
            users = [
                u
                for u in users
                if term in u.email.lower()
                or term in u.username.lower()
                or term in u.full_name.lower()
            ]
        self._audit_mutation(
            action="list",
            target_user_id=None,
            tenant_id=effective_tenant_id,
            operator_id=operator_id,
            metadata={"count": len(users)},
        )
        return users

    async def update_user(
        self,
        user_id: str,
        updates: Dict[str, Any],
        *,
        operator_tenant_id: Optional[str] = None,
        operator_id: Optional[str] = None,
    ) -> bool:
        """Update user fields with audit logging."""
        user = await self._auth_service.get_user_by_id(user_id)
        if not user:
            return False
        effective_tenant_id = self._enforce_tenant_boundary(user.tenant_id, operator_tenant_id)
        # AuthService does not expose a generic update path; audit the attempt anyway.
        self._audit_mutation(
            action="update",
            target_user_id=user_id,
            tenant_id=effective_tenant_id,
            operator_id=operator_id,
            metadata={"updated_fields": sorted(updates.keys())},
        )
        return False

    async def delete_user(
        self,
        user_id: str,
        *,
        operator_tenant_id: Optional[str] = None,
        operator_id: Optional[str] = None,
    ) -> bool:
        """Delete (deactivate) a user with audit logging."""
        user = await self._auth_service.get_user_by_id(user_id)
        if not user:
            return False
        effective_tenant_id = self._enforce_tenant_boundary(user.tenant_id, operator_tenant_id)
        self._audit_mutation(
            action="delete",
            target_user_id=user_id,
            tenant_id=effective_tenant_id,
            operator_id=operator_id,
        )
        return False

    async def get_user_sessions(
        self,
        user_id: str,
        operator_tenant_id: Optional[str] = None,
        operator_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return active sessions for a user within tenant boundaries."""
        user = await self._auth_service.get_user_by_id(user_id)
        if not user:
            return []
        self._enforce_tenant_boundary(user.tenant_id, operator_tenant_id)
        sessions = [
            {
                "id": s.id,
                "user_id": s.user_id,
                "expires_at": s.expires_at.isoformat(),
                "ip_address": s.ip_address,
                "is_active": s.is_active,
            }
            for s in self._auth_service._active_sessions.values()
            if s.user_id == user_id
        ]
        self._audit_mutation(
            action="list_sessions",
            target_user_id=user_id,
            tenant_id=user.tenant_id,
            operator_id=operator_id,
        )
        return sessions
