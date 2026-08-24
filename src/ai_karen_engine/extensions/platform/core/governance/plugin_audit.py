"""
Plugin audit logger.

Emits structured audit events for every plugin invocation with the required
observability fields:

    plugin_id
    plugin_version
    tenant_id
    user_id
    correlation_id
    permission_set
    execution_ms
    status
    error_code
    side_effects
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("kari.plugin_governance.audit")


@dataclass
class PluginAuditEvent:
    plugin_id: str
    plugin_version: str
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    correlation_id: Optional[str] = None
    stage: str = "execution"
    outcome: str = "unknown"
    permission_set: List[str] = field(default_factory=list)
    error_code: Optional[str] = None
    detail: str = ""
    side_effects: List[str] = field(default_factory=list)
    execution_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
            "stage": self.stage,
            "outcome": self.outcome,
            "permission_set": list(self.permission_set),
            "error_code": self.error_code,
            "detail": self.detail,
            "side_effects": list(self.side_effects),
            "execution_ms": self.execution_ms,
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
        }


class PluginAuditLogger:
    """Structured audit logger for plugin governance events."""

    def __init__(self, sink: Optional[Callable[[PluginAuditEvent], None]] = None):
        self._sink = sink
        self._events: List[PluginAuditEvent] = []
        self._max_history = 10000

    def log(self, event: PluginAuditEvent) -> None:
        self._events.append(event)
        if len(self._events) > self._max_history:
            self._events = self._events[-self._max_history :]

        if self._sink:
            try:
                self._sink(event)
            except Exception as exc:
                logger.warning("Audit sink failed: %s", exc)

        logger.info(
            "plugin_audit plugin_id=%s plugin_version=%s tenant_id=%s user_id=%s correlation_id=%s stage=%s outcome=%s error_code=%s execution_ms=%s side_effects=%s detail=%s",
            event.plugin_id,
            event.plugin_version,
            event.tenant_id,
            event.user_id,
            event.correlation_id,
            event.stage,
            event.outcome,
            event.error_code,
            event.execution_ms,
            event.side_effects,
            event.detail,
        )

    def record_execution(
        self,
        *,
        plugin_id: str,
        plugin_version: str,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        status: str,
        error_code: Optional[str] = None,
        side_effects: Optional[List[str]] = None,
        execution_ms: Optional[float] = None,
        permission_set: Optional[List[str]] = None,
        detail: str = "",
    ) -> PluginAuditEvent:
        start = time.perf_counter()
        event = PluginAuditEvent(
            plugin_id=plugin_id,
            plugin_version=plugin_version,
            tenant_id=tenant_id,
            user_id=user_id,
            correlation_id=correlation_id,
            stage="execution",
            outcome=status,
            error_code=error_code,
            side_effects=side_effects or [],
            execution_ms=execution_ms,
            permission_set=permission_set or [],
            detail=detail,
        )
        self.log(event)
        return event

    def history(self, limit: int = 1000) -> List[PluginAuditEvent]:
        return list(self._events[-limit:])

    def clear(self) -> None:
        self._events.clear()


__all__ = ["PluginAuditEvent", "PluginAuditLogger"]
