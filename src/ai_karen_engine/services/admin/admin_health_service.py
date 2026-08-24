"""
Admin Health Service — wraps health checks with normalized status
and tenant-aware observability.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
    ChatRuntimeControlPlane,
    RuntimeMode,
    DependencyStatus,
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


@dataclass
class NormalizedDependencyHealth:
    """Normalized dependency health for admin consumption."""

    name: str
    status: str
    reason: Optional[str]
    response_time_ms: float
    consecutive_successes: int
    consecutive_failures: int
    checked_at: Optional[str]


@dataclass
class NormalizedRuntimeStatus:
    """Normalized runtime status for admin consumption."""

    mode: str
    maintenance_active: bool
    maintenance_message: Optional[str]
    estimated_completion_time: Optional[str]
    normal_ready: bool
    degraded_ready: bool
    last_transition_at: Optional[str]
    last_transition_reason: Optional[str]


class AdminHealthService:
    """
    Admin-facing wrapper around ChatRuntimeControlPlane and health checks.

    Adds:
    - Normalized status responses
    - Tenant-aware health summaries
    - Audit logging for health check triggers
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
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit an admin audit event for a health action."""
        event = AuditEvent(
            event_type=AuditEventType.SYSTEM_EVENT,
            severity=AuditSeverity.INFO,
            message=f"admin_health_{action}",
            user_id=operator_id,
            metadata=metadata or {},
        )
        self._audit.log_audit_event(event)

    async def get_runtime_status(
        self,
        operator_id: Optional[str] = None,
    ) -> NormalizedRuntimeStatus:
        """Return normalized runtime status."""
        snapshot = self._control_plane.get_snapshot()
        self._audit_mutation(
            action="status_read",
            operator_id=operator_id,
        )
        return NormalizedRuntimeStatus(
            mode=snapshot.mode.value,
            maintenance_active=snapshot.maintenance_active,
            maintenance_message=snapshot.maintenance_message,
            estimated_completion_time=snapshot.estimated_completion_time,
            normal_ready=snapshot.normal_ready,
            degraded_ready=snapshot.degraded_ready,
            last_transition_at=snapshot.last_transition_at,
            last_transition_reason=snapshot.last_transition_reason,
        )

    async def get_dependency_health(
        self,
        operator_id: Optional[str] = None,
    ) -> List[NormalizedDependencyHealth]:
        """Return normalized dependency health."""
        snapshot = self._control_plane.get_snapshot()
        deps = []
        for name, health in snapshot.dependencies.items():
            deps.append(
                NormalizedDependencyHealth(
                    name=name,
                    status=health.status.value,
                    reason=health.reason,
                    response_time_ms=health.response_time_ms,
                    consecutive_successes=health.consecutive_successes,
                    consecutive_failures=health.consecutive_failures,
                    checked_at=health.checked_at.isoformat() if health.checked_at else None,
                )
            )
        self._audit_mutation(
            action="dependency_health_read",
            operator_id=operator_id,
            metadata={"dependency_count": len(deps)},
        )
        return deps

    async def trigger_health_check(
        self,
        operator_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Trigger an immediate health check with audit logging."""
        await self._control_plane._run_health_checks()
        snapshot = self._control_plane.get_snapshot()
        self._audit_mutation(
            action="triggered",
            operator_id=operator_id,
            metadata={
                "mode": snapshot.mode.value,
                "normal_ready": snapshot.normal_ready,
                "degraded_ready": snapshot.degraded_ready,
            },
        )
        return {
            "mode": snapshot.mode.value,
            "normal_ready": snapshot.normal_ready,
            "degraded_ready": snapshot.degraded_ready,
            "message": "Health check completed",
        }
