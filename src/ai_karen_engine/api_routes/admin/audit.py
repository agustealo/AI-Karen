from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ai_karen_engine.auth.rbac_middleware import (
    Permission,
    require_permission,
)
from ai_karen_engine.services.admin.admin_audit_service import AdminAuditService
from ai_karen_engine.services.audit.audit_logging import (
    AuditEventType,
    AuditSeverity,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/audit", tags=["admin-audit"])


class AdminAuditLogResponse(BaseModel):
    events: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int


class AdminAuditSummaryResponse(BaseModel):
    count: int
    by_type: Dict[str, int]
    by_severity: Dict[str, int]
    tenants: List[str]
    users: List[str]


def get_admin_audit_service() -> AdminAuditService:
    return AdminAuditService()


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


@router.get("/logs", response_model=AdminAuditLogResponse)
async def list_admin_audit_logs(
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_AUDIT_READ)),
    event_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None, description="Filter by action metadata field"),
    resource: Optional[str] = Query(None, description="Filter by resource metadata field"),
    status: Optional[str] = Query(None, description="Filter by granted/denied status in metadata"),
    correlation_id: Optional[str] = Query(None),
    request_id: Optional[str] = Query(None),
    error_code: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Searchable audit trail with full filters (admin read)."""
    service = get_admin_audit_service()
    from ai_karen_engine.services.admin.admin_audit_service import AdminAuditFilter

    audit_filter = AdminAuditFilter(
        event_type=AuditEventType(event_type) if event_type else None,
        severity=AuditSeverity(severity) if severity else None,
        user_id=user_id,
        tenant_id=tenant_id,
        start_time=_parse_datetime(start_time),
        end_time=_parse_datetime(end_time),
        limit=limit,
        offset=offset,
    )
    events = service.get_recent_events(audit_filter=audit_filter)

    if action:
        events = [e for e in events if e.get("metadata", {}).get("action") == action]
    if resource:
        events = [e for e in events if e.get("metadata", {}).get("resource") == resource]
    if status:
        events = [e for e in events if str(e.get("metadata", {}).get("granted")) == status]
    if correlation_id:
        events = [e for e in events if e.get("metadata", {}).get("correlation_id") == correlation_id]
    if request_id:
        events = [e for e in events if e.get("metadata", {}).get("request_id") == request_id]
    if error_code:
        events = [e for e in events if e.get("metadata", {}).get("error_code") == error_code]

    return AdminAuditLogResponse(
        events=events,
        total=len(events),
        limit=limit,
        offset=offset,
    )


@router.get("/summary", response_model=AdminAuditSummaryResponse)
async def get_admin_audit_summary(
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_AUDIT_READ)),
    tenant_id: Optional[str] = Query(None),
):
    """Get audit summary for dashboard (admin read)."""
    service = get_admin_audit_service()
    from ai_karen_engine.services.admin.admin_audit_service import AdminAuditFilter

    audit_filter = AdminAuditFilter(tenant_id=tenant_id)
    summary = service.get_summary(audit_filter=audit_filter)
    return AdminAuditSummaryResponse(**summary)


@router.post("/log")
async def log_admin_audit_event(
    event: Dict[str, Any],
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_AUDIT_READ)),
):
    """Log a custom admin audit event."""
    service = get_admin_audit_service()
    service.log_admin_action(
        action=event.get("action", "custom"),
        operator_id=current_user.get("user_id"),
        tenant_id=current_user.get("tenant_id"),
        metadata=event.get("metadata", {}),
    )
    return {"status": "success"}
