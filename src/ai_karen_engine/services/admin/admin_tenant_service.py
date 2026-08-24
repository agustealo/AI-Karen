"""
Admin Tenant Service — wraps TenantManager with admin-specific logic,
audit logging, and tenant-aware operations.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from ai_karen_engine.database.tenant_manager import (
    TenantManager,
    TenantConfig,
    TenantStats,
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
class AdminTenantFilter:
    """Filter criteria for admin tenant listing."""

    subscription_tier: Optional[str] = None
    active_only: bool = True
    limit: int = 100
    offset: int = 0


class AdminTenantService:
    """
    Admin-facing wrapper around TenantManager.

    Adds:
    - Structured audit events for all mutations
    - Admin-specific filtering and pagination
    - Tenant stats normalization
    """

    def __init__(self, tenant_manager: TenantManager) -> None:
        self._tenant_manager = tenant_manager
        self._audit = get_audit_logger()

    def _audit_mutation(
        self,
        action: str,
        tenant_id: Optional[str],
        operator_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit an admin audit event for a tenant mutation."""
        event = AuditEvent(
            event_type=AuditEventType.SYSTEM_EVENT,
            severity=AuditSeverity.INFO,
            message=f"admin_tenant_{action}",
            user_id=operator_id,
            tenant_id=tenant_id,
            metadata={
                "action": action,
                **(metadata or {}),
            },
        )
        self._audit.log_audit_event(event)

    async def create_tenant(
        self,
        config: TenantConfig,
        admin_email: str,
        admin_roles: Optional[List[str]] = None,
        *,
        operator_id: Optional[str] = None,
    ) -> Optional[Any]:
        """Create a tenant with audit logging."""
        tenant = await self._tenant_manager.create_tenant(
            config=config,
            admin_email=admin_email,
            admin_roles=admin_roles,
        )
        self._audit_mutation(
            action="create",
            tenant_id=str(tenant.id),
            operator_id=operator_id,
            metadata={
                "name": config.name,
                "slug": config.slug,
                "subscription_tier": config.subscription_tier,
            },
        )
        return tenant

    async def get_tenant(
        self,
        tenant_id: Union[str, uuid.UUID],
        operator_id: Optional[str] = None,
    ) -> Optional[Any]:
        """Get a tenant by id with audit logging."""
        tenant = await self._tenant_manager.get_tenant(tenant_id)
        if tenant:
            self._audit_mutation(
                action="read",
                tenant_id=str(tenant.id),
                operator_id=operator_id,
            )
        return tenant

    async def list_tenants(
        self,
        tenant_filter: AdminTenantFilter,
        operator_id: Optional[str] = None,
    ) -> List[Any]:
        """List tenants with admin filtering."""
        tenants = await self._tenant_manager.list_tenants(
            active_only=tenant_filter.active_only,
            limit=tenant_filter.limit,
            offset=tenant_filter.offset,
        )
        if tenant_filter.subscription_tier:
            tenants = [
                t for t in tenants if t.settings.get("subscription_tier") == tenant_filter.subscription_tier
            ]
        self._audit_mutation(
            action="list",
            tenant_id=None,
            operator_id=operator_id,
            metadata={"count": len(tenants)},
        )
        return tenants

    async def update_tenant(
        self,
        tenant_id: Union[str, uuid.UUID],
        updates: Dict[str, Any],
        *,
        operator_id: Optional[str] = None,
    ) -> bool:
        """Update a tenant with audit logging."""
        result = await self._tenant_manager.update_tenant(tenant_id, updates)
        if result:
            self._audit_mutation(
                action="update",
                tenant_id=str(tenant_id),
                operator_id=operator_id,
                metadata={"updated_fields": sorted(updates.keys())},
            )
        return result

    async def delete_tenant(
        self,
        tenant_id: Union[str, uuid.UUID],
        *,
        operator_id: Optional[str] = None,
    ) -> bool:
        """Delete a tenant with audit logging."""
        result = await self._tenant_manager.delete_tenant(tenant_id)
        if result:
            self._audit_mutation(
                action="delete",
                tenant_id=str(tenant_id),
                operator_id=operator_id,
            )
        return result

    async def get_tenant_stats(
        self,
        tenant_id: Union[str, uuid.UUID],
        operator_id: Optional[str] = None,
    ) -> Optional[TenantStats]:
        """Get tenant stats with audit logging."""
        stats = await self._tenant_manager.get_tenant_stats(tenant_id)
        if stats:
            self._audit_mutation(
                action="read_stats",
                tenant_id=tenant_id,
                operator_id=operator_id,
            )
        return stats
