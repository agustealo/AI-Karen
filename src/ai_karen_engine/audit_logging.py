"""
Fallback audit logging utilities used across the services layer.

This module contains the minimal surface area required by auth and secure storage
paths that previously imported ``ai_karen_engine.services.audit_logging``. Having
the implementation under ``services`` lets the compatibility shim redirect legacy
imports without duplicating logic.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Union


class AuditEventType(str, Enum):
    """Supported audit event categories (minimal set used across the app)."""

    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    ACCESS_GRANTED = "access_granted"
    ACCESS_DENIED = "access_denied"
    API_REQUEST_PERFORMANCE = "api_request_performance"
    SECURITY_EVENT = "security_event"
    SYSTEM_EVENT = "system_event"


class AuditSeverity(str, Enum):
    """Audit event severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AuditEvent:
    """Structured audit event payload."""

    event_type: Union[AuditEventType, str]
    severity: Union[AuditSeverity, str]
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    session_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    correlation_id: Optional[str] = None
    endpoint: Optional[str] = None
    method: Optional[str] = None
    status_code: Optional[int] = None
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class AuditLogger:
    """Simple audit logger that emits JSON lines to the Kari audit logger."""

    def __init__(self) -> None:
        self._logger = logging.getLogger("kari.audit")
        self._logger.setLevel(logging.INFO)
        # Avoid duplicate handlers when hot-reloading
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
        self._logger.propagate = False
        self._recent_events: Deque[Dict[str, Any]] = deque(maxlen=1000)

    def _normalize_event(self, event: Union[AuditEvent, Dict[str, Any]]) -> Dict[str, Any]:
        """Convert supported event inputs into a JSON-serialisable dict."""
        if isinstance(event, AuditEvent):
            data = asdict(event)
            data["event_type"] = (
                event.event_type.value if isinstance(event.event_type, Enum) else str(event.event_type)
            )
            data["severity"] = (
                event.severity.value if isinstance(event.severity, Enum) else str(event.severity)
            )
            data["timestamp"] = event.timestamp.isoformat()
            return data

        if isinstance(event, dict):
            data = dict(event)
            # Normalise enum-like values for downstream JSON logging
            if isinstance(data.get("event_type"), Enum):
                data["event_type"] = data["event_type"].value  # type: ignore[index]
            if isinstance(data.get("severity"), Enum):
                data["severity"] = data["severity"].value  # type: ignore[index]
            data.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
            return data

        raise TypeError(f"Unsupported audit event type: {type(event)}")

    def log_audit_event(self, event: Union[AuditEvent, Dict[str, Any]]) -> None:
        """Log an audit event. Accepts either the dataclass or a plain dict."""
        payload = self._normalize_event(event)
        self._recent_events.append(payload)
        try:
            self._logger.info(json.dumps(payload, default=str))
        except Exception:
            # Never let audit logging crash the request path
            self._logger.info(str(payload))

    def get_recent_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return recent audit events for observability surfaces."""
        if limit <= 0:
            return []
        return list(self._recent_events)[-limit:]

    def get_event_counts(self) -> Dict[str, int]:
        """Return event counts grouped by event type."""
        counts: Dict[str, int] = {}
        for event in self._recent_events:
            event_type = str(event.get("event_type") or "unknown")
            counts[event_type] = counts.get(event_type, 0) + 1
        return counts

    def log_cloud_usage(self, user_id: str, provider: str, model: str) -> None:
        """Compatibility helper used by model orchestrator audit hooks."""
        self.log_audit_event(
            {
                "event_type": AuditEventType.SECURITY_EVENT.value,
                "severity": AuditSeverity.INFO.value,
                "message": "cloud_usage",
                "user_id": user_id,
                "metadata": {"provider": provider, "model": model},
            }
        )

    def log_error_response_generated(
        self,
        error_category: str,
        error_severity: str,
        provider_name: Optional[str] = None,
        ai_analysis_used: bool = False,
        response_cached: bool = False,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Log generation of an intelligent error response."""
        self.log_audit_event(
            {
                "event_type": AuditEventType.SECURITY_EVENT.value,
                "severity": AuditSeverity.WARNING.value
                if error_severity in ("critical", "high")
                else AuditSeverity.INFO.value,
                "message": "error_response_generated",
                "user_id": user_id,
                "tenant_id": tenant_id,
                "metadata": {
                    "error_category": error_category,
                    "error_severity": error_severity,
                    "provider_name": provider_name,
                    "ai_analysis_used": ai_analysis_used,
                    "response_cached": response_cached,
                    "correlation_id": correlation_id,
                },
            }
        )

    def log_response_cache_event(
        self,
        cache_hit: bool,
        error_category: Optional[str] = None,
        additional_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log cache events for error responses."""
        self.log_audit_event(
            {
                "event_type": AuditEventType.SYSTEM_EVENT.value,
                "severity": AuditSeverity.INFO.value,
                "message": "error_response_cache_hit" if cache_hit else "error_response_cached",
                "metadata": {
                    "cache_hit": cache_hit,
                    "error_category": error_category,
                    "additional_context": additional_context,
                },
            }
        )


_AUDIT_LOGGER: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Return a shared audit logger instance."""
    global _AUDIT_LOGGER
    if _AUDIT_LOGGER is None:
        _AUDIT_LOGGER = AuditLogger()
    return _AUDIT_LOGGER


__all__ = [
    "AuditEvent",
    "AuditEventType",
    "AuditLogger",
    "AuditSeverity",
    "get_audit_logger",
]
