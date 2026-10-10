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

    async def list_users_page(
        self,
        user_filter: AdminUserFilter,
        operator_tenant_id: Optional[str] = None,
        operator_id: Optional[str] = None,
    ) -> tuple[List[UserAccount], int]:
        """Delegate filtering and counting to the canonical durable query."""
        tenant_id = self._enforce_tenant_boundary(
            user_filter.tenant_id, operator_tenant_id
        )
        if not tenant_id:
            raise PermissionError("Tenant context required")
        users, total = await self._auth_service.list_users_page(
            tenant_id=tenant_id,
            role=user_filter.role,
            status=user_filter.status,
            search=user_filter.search,
            limit=user_filter.limit,
            offset=user_filter.offset,
        )
        self._audit_mutation(
            action="list", target_user_id=None, tenant_id=tenant_id,
            operator_id=operator_id, metadata={"count": len(users), "total": total},
        )
        return users, total

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
        allowed = {"full_name", "roles", "is_active", "is_verified"}
        if not updates or set(updates) - allowed:
            raise ValueError("Invalid admin user update fields")
        roles = updates.get("roles")
        if roles is not None:
            try:
                roles = [UserRole(role).value for role in roles]
            except (ValueError, TypeError) as exc:
                raise ValueError("Invalid user role") from exc
            if not roles:
                raise ValueError("User must retain at least one role")
        if user_id == operator_id and (
            updates.get("is_active") is False
            or (roles is not None and UserRole.ADMIN.value not in roles)
        ):
            raise PermissionError("Cannot remove your own admin access")
        profile_changes = {
            key: value for key, value in updates.items()
            if key != "is_active"
        }
        if roles is not None:
            profile_changes["roles"] = roles
        if profile_changes:
            await self._auth_service.update_user(user_id, **profile_changes)
        if updates.get("is_active") is not None:
            await self._auth_service.set_user_status(
                user_id, updates["is_active"], reason="admin_account_status_change"
            )
        self._audit_mutation(
            action="update",
            target_user_id=user_id,
            tenant_id=effective_tenant_id,
            operator_id=operator_id,
            metadata={"updated_fields": sorted(updates.keys())},
        )
        return True

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
        if operator_id == user_id:
            raise PermissionError("Cannot deactivate your own account")
        await self._auth_service.set_user_status(
            user_id, False, reason="admin_account_deactivation"
        )
        self._audit_mutation(
            action="deactivate",
            target_user_id=user_id,
            tenant_id=effective_tenant_id,
            operator_id=operator_id,
        )
        return True

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
        # Canonical durable session source. Never expose bearer or refresh tokens.
        durable_sessions = await self._auth_service.list_sessions(
            user_id=user_id, active_only=True, strict_errors=True
        )
        sessions = [
            {
                "id": entry["session_token"],
                "user_id": entry["user_id"],
                "created_at": entry.get("created_at"),
                "last_accessed": entry.get("last_accessed"),
                "ip_address": entry.get("ip_address"),
                "user_agent": entry.get("user_agent"),
                "is_active": entry["is_active"],
            }
            for entry in durable_sessions
        ]
        self._audit_mutation(
            action="list_sessions",
            target_user_id=user_id,
            tenant_id=user.tenant_id,
            operator_id=operator_id,
        )
        return sessions
