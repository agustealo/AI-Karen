"""
Admin Runtime Service — wraps ChatRuntimeControlPlane with admin-specific
logic, audit logging, and tenant-aware operations.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
    ChatRuntimeControlPlane,
    RuntimeMode,
    get_chat_runtime_control_plane,
)
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.services.audit.audit_logging import (
    AuditEvent,
    AuditEventType,
    AuditSeverity,
    get_audit_logger,
)

logger = get_logger(__name__)


class AdminRuntimeService:
    """
    Admin-facing wrapper around ChatRuntimeControlPlane.

    Adds:
    - Structured audit events for all mutations
    - Admin-specific mode transition validation helpers
    - Maintenance notification subscription listing
    - Tenant boundary enforcement (runtime is global but actions are attributed)
    """

    def __init__(self, control_plane: Optional[ChatRuntimeControlPlane] = None) -> None:
        self._control_plane = control_plane
        self._audit = get_audit_logger()

    async def initialize(self) -> None:
        if self._control_plane is None:
            self._control_plane = await get_chat_runtime_control_plane()

    def _audit_mutation(
        self,
        action: str,
        operator_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit an admin audit event for a runtime mutation."""
        event = AuditEvent(
            event_type=AuditEventType.SYSTEM_EVENT,
            severity=AuditSeverity.INFO,
            message=f"admin_runtime_{action}",
            user_id=operator_id,
            tenant_id=tenant_id,
            metadata=metadata or {},
        )
        self._audit.log_audit_event(event)

    async def get_status(
        self,
        operator_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return current runtime mode and dependency health."""
        snapshot = self._control_plane.get_snapshot()
        deps = {}
        for name, health in snapshot.dependencies.items():
            deps[name] = {
                "status": health.status.value,
                "reason": health.reason,
                "response_time_ms": health.response_time_ms,
                "consecutive_successes": health.consecutive_successes,
                "consecutive_failures": health.consecutive_failures,
                "checked_at": health.checked_at.isoformat() if health.checked_at else None,
            }
        self._audit_mutation(
            action="status_read",
            operator_id=operator_id,
            metadata={"mode": snapshot.mode.value},
        )
        return {
            "mode": snapshot.mode.value,
            "maintenance_active": snapshot.maintenance_active,
            "maintenance_message": snapshot.maintenance_message,
            "estimated_completion_time": snapshot.estimated_completion_time,
            "normal_ready": snapshot.normal_ready,
            "degraded_ready": snapshot.degraded_ready,
            "degraded_capabilities": (
                {
                    "memory": snapshot.degraded_capabilities.memory_available,
                    "tools": snapshot.degraded_capabilities.tools_available,
                    "plugins": snapshot.degraded_capabilities.plugins_available,
                    "external_providers": snapshot.degraded_capabilities.external_providers_available,
                    "streaming": snapshot.degraded_capabilities.streaming_supported,
                    "description": snapshot.degraded_capabilities.description,
                }
                if snapshot.degraded_capabilities
                else None
            ),
            "dependencies": deps,
            "last_transition_at": snapshot.last_transition_at,
            "last_transition_reason": snapshot.last_transition_reason,
        }

    async def transition_mode(
        self,
        new_mode: RuntimeMode,
        reason: str,
        *,
        operator_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> bool:
        """Request a runtime mode transition with audit logging."""
        success = await self._control_plane.transition_mode(new_mode, reason)
        self._audit_mutation(
            action="transition_mode",
            operator_id=operator_id,
            tenant_id=tenant_id,
            metadata={
                "new_mode": new_mode.value,
                "reason": reason,
                "success": success,
            },
        )
        return success

    async def enable_maintenance(
        self,
        reason: str,
        message: str,
        estimated_completion_time: Optional[datetime] = None,
        auto_end_policy: str = "manual",
        *,
        operator_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> bool:
        """Enable maintenance mode with audit logging."""
        success = await self._control_plane.enable_maintenance(
            reason=reason,
            message=message,
            estimated_completion_time=estimated_completion_time,
            auto_end_policy=auto_end_policy,
            created_by=operator_id,
        )
        self._audit_mutation(
            action="enable_maintenance",
            operator_id=operator_id,
            tenant_id=tenant_id,
            metadata={
                "reason": reason,
                "message": message,
                "estimated_completion_time": (
                    estimated_completion_time.isoformat() if estimated_completion_time else None
                ),
                "auto_end_policy": auto_end_policy,
                "success": success,
            },
        )
        return success

    async def disable_maintenance(
        self,
        *,
        operator_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> bool:
        """Disable maintenance mode with audit logging."""
        success = await self._control_plane.disable_maintenance(updated_by=operator_id)
        self._audit_mutation(
            action="disable_maintenance",
            operator_id=operator_id,
            tenant_id=tenant_id,
            metadata={"success": success},
        )
        return success

    async def update_maintenance(
        self,
        *,
        message: Optional[str] = None,
        estimated_completion_time: Optional[datetime] = None,
        auto_end_policy: Optional[str] = None,
        operator_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> bool:
        """Update the active maintenance window with audit logging."""
        success = await self._control_plane.update_maintenance(
            message=message,
            estimated_completion_time=estimated_completion_time,
            auto_end_policy=auto_end_policy,
            updated_by=operator_id,
        )
        self._audit_mutation(
            action="update_maintenance",
            operator_id=operator_id,
            tenant_id=tenant_id,
            metadata={
                "message_updated": message is not None,
                "eta_updated": estimated_completion_time is not None,
                "auto_end_policy_updated": auto_end_policy is not None,
                "success": success,
            },
        )
        return success

    async def get_notification_subscriptions(
        self,
        limit: int = 100,
        operator_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return maintenance notification subscriptions with audit logging."""
        subscriptions = await self._control_plane.get_maintenance_notification_subscriptions(limit=limit)
        self._audit_mutation(
            action="list_notifications",
            operator_id=operator_id,
            metadata={"count": len(subscriptions)},
        )
        return subscriptions

    async def get_runtime_events(
        self,
        limit: int = 50,
        operator_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get recent runtime events with audit logging."""
        try:
            from ai_karen_engine.database.client import MultiTenantPostgresClient
            from ai_karen_engine.database.models import ChatRuntimeEvent
            from sqlalchemy import select

            db = MultiTenantPostgresClient()
            async with db.get_async_session() as session:
                result = await session.execute(
                    select(ChatRuntimeEvent)
                    .order_by(ChatRuntimeEvent.created_at.desc())
                    .limit(min(limit, 200))
                )
                events = result.scalars().all()

            events_payload = [
                {
                    "id": str(ev.id),
                    "event_type": ev.event_type,
                    "mode": ev.mode,
                    "details": ev.details_json,
                    "created_at": ev.created_at.isoformat() if ev.created_at else None,
                }
                for ev in events
            ]
            self._audit_mutation(
                action="list_events",
                operator_id=operator_id,
                metadata={"count": len(events_payload)},
            )
            return {
                "events": events_payload,
                "count": len(events_payload),
            }
        except Exception as exc:
            logger.error("Failed to fetch runtime events: %s", exc)
            return {"events": [], "count": 0, "error": str(exc)}
