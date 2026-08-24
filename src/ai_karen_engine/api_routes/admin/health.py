from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ai_karen_engine.auth.rbac_middleware import (
    Permission,
    require_permission,
)
from ai_karen_engine.services.admin.admin_health_service import AdminHealthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/health", tags=["admin-health"])


class AdminHealthDependencyResponse(BaseModel):
    name: str
    status: str
    reason: Optional[str]
    response_time_ms: float
    consecutive_successes: int
    consecutive_failures: int
    checked_at: Optional[str]


class AdminHealthStatusResponse(BaseModel):
    status: str
    dependencies: List[AdminHealthDependencyResponse]
    mode: str
    normal_ready: bool
    degraded_ready: bool
    last_transition_at: Optional[str]
    last_transition_reason: Optional[str]


def get_admin_health_service() -> AdminHealthService:
    return AdminHealthService()


def _normalize_health(status: str) -> str:
    normalized = status.lower()
    if normalized in ("healthy", "ok", "up", "available"):
        return "healthy"
    if normalized in ("degraded", "slow", "partial"):
        return "degraded"
    if normalized in ("unhealthy", "down", "unavailable", "error", "failed"):
        return "unavailable"
    return "unknown"


@router.get("/", response_model=AdminHealthStatusResponse)
async def get_admin_health_status(
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_HEALTH_READ)),
):
    """System health dashboard with explicit normalized states (admin read)."""
    service = get_admin_health_service()
    runtime = await service.get_runtime_status(operator_id=current_user.get("user_id"))
    deps = await service.get_dependency_health(operator_id=current_user.get("user_id"))

    normalized_deps = [
        AdminHealthDependencyResponse(
            name=d.name,
            status=_normalize_health(d.status),
            reason=d.reason,
            response_time_ms=d.response_time_ms,
            consecutive_successes=d.consecutive_successes,
            consecutive_failures=d.consecutive_failures,
            checked_at=d.checked_at,
        )
        for d in deps
    ]

    overall = "healthy"
    if any(d.status == "unavailable" for d in normalized_deps):
        overall = "unavailable"
    elif any(d.status == "degraded" for d in normalized_deps):
        overall = "degraded"

    return AdminHealthStatusResponse(
        status=overall,
        dependencies=normalized_deps,
        mode=runtime.mode,
        normal_ready=runtime.normal_ready,
        degraded_ready=runtime.degraded_ready,
        last_transition_at=runtime.last_transition_at,
        last_transition_reason=runtime.last_transition_reason,
    )


@router.post("/check")
async def trigger_admin_health_check(
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_HEALTH_READ)),
):
    """Trigger an immediate health check (admin read)."""
    service = get_admin_health_service()
    result = await service.trigger_health_check(operator_id=current_user.get("user_id"))
    return result
