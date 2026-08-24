"""
Admin Audit Service — wraps the audit logger with enhanced querying,
filtering, and tenant-aware observability.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from ai_karen_engine.services.audit.audit_logging import (
    AuditEvent,
    AuditEventType,
    AuditSeverity,
    AuditLogger,
    get_audit_logger,
)
from ai_karen_engine.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class AdminAuditFilter:
    """Filter criteria for admin audit querying."""

    event_type: Optional[Union[AuditEventType, str]] = None
    severity: Optional[Union[AuditSeverity, str]] = None
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    limit: int = 100
    offset: int = 0


class AdminAuditService:
    """
    Admin-facing wrapper around AuditLogger.

    Adds:
    - Enhanced querying with filters
    - Tenant-aware event retrieval
    - Event count aggregation by type/severity
    - Structured summaries for dashboards
    """

    def __init__(self, audit_logger: Optional[AuditLogger] = None) -> None:
        self._audit_logger = audit_logger or get_audit_logger()

    def get_recent_events(
        self,
        audit_filter: AdminAuditFilter,
    ) -> List[Dict[str, Any]]:
        """Return recent audit events matching the admin filter."""
        events = self._audit_logger.get_recent_events(limit=audit_filter.limit + audit_filter.offset)
        if audit_filter.event_type:
            expected = (
                audit_filter.event_type.value
                if isinstance(audit_filter.event_type, AuditEventType)
                else str(audit_filter.event_type)
            )
            events = [e for e in events if str(e.get("event_type")) == expected]
        if audit_filter.severity:
            expected = (
                audit_filter.severity.value
                if isinstance(audit_filter.severity, AuditSeverity)
                else str(audit_filter.severity)
            )
            events = [e for e in events if str(e.get("severity")) == expected]
        if audit_filter.user_id:
            events = [e for e in events if e.get("user_id") == audit_filter.user_id]
        if audit_filter.tenant_id:
            events = [e for e in events if e.get("tenant_id") == audit_filter.tenant_id]
        if audit_filter.start_time:
            events = [
                e
                for e in events
                if datetime.fromisoformat(e.get("timestamp", "")) >= audit_filter.start_time
            ]
        if audit_filter.end_time:
            events = [
                e
                for e in events
                if datetime.fromisoformat(e.get("timestamp", "")) <= audit_filter.end_time
            ]
        events = events[audit_filter.offset : audit_filter.offset + audit_filter.limit]
        return events

    def get_event_counts(
        self,
        *,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, int]:
        """Return event counts, optionally filtered by tenant."""
        counts = self._audit_logger.get_event_counts()
        if not tenant_id:
            return counts
        filtered_counts: Dict[str, int] = {}
        for event in self._audit_logger.get_recent_events(limit=1000):
            if event.get("tenant_id") != tenant_id:
                continue
            event_type = str(event.get("event_type") or "unknown")
            filtered_counts[event_type] = filtered_counts.get(event_type, 0) + 1
        return filtered_counts

    def get_summary(
        self,
        audit_filter: AdminAuditFilter,
    ) -> Dict[str, Any]:
        """Return a summary of audit events for dashboard consumption."""
        events = self.get_recent_events(audit_filter)
        by_type: Dict[str, int] = {}
        by_severity: Dict[str, int] = {}
        tenants: set = set()
        users: set = set()
        for event in events:
            by_type[str(event.get("event_type") or "unknown")] = by_type.get(str(event.get("event_type") or "unknown"), 0) + 1
            by_severity[str(event.get("severity") or "unknown")] = by_severity.get(str(event.get("severity") or "unknown"), 0) + 1
            if event.get("tenant_id"):
                tenants.add(event["tenant_id"])
            if event.get("user_id"):
                users.add(event["user_id"])
        return {
            "count": len(events),
            "by_type": by_type,
            "by_severity": by_severity,
            "tenants": sorted(tenants),
            "users": sorted(users),
        }

    def log_admin_action(
        self,
        action: str,
        *,
        operator_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log an admin action directly through the underlying audit logger."""
        event = AuditEvent(
            event_type=AuditEventType.SYSTEM_EVENT,
            severity=AuditSeverity.INFO,
            message=f"admin_{action}",
            user_id=operator_id,
            tenant_id=tenant_id,
            metadata=metadata or {},
        )
        self._audit_logger.log_audit_event(event)
