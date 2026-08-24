from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ai_karen_engine.auth.rbac_middleware import (
    Permission,
    require_permission,
)
from ai_karen_engine.services.admin.admin_runtime_service import AdminRuntimeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/runtime", tags=["admin-runtime"])


class EnableMaintenanceRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)
    message: str = Field(..., min_length=1, max_length=2000)
    estimated_completion_time: Optional[str] = Field(
        None, description="ISO 8601 datetime string for ETA"
    )
    auto_end_policy: str = Field(
        "manual",
        pattern=r"^(manual|after_healthy_check|at_time)$",
    )


class UpdateMaintenanceRequest(BaseModel):
    message: Optional[str] = Field(None, max_length=2000)
    estimated_completion_time: Optional[str] = None
    auto_end_policy: Optional[str] = Field(None, pattern=r"^(manual|after_healthy_check|at_time)$")


class CleanupRequest(BaseModel):
    dry_run: bool = Field(True)
    categories: Optional[List[str]] = Field(
        None, description="Specific categories to clean (files, users, cache, backups)"
    )


_runtime_service_instance: Optional[AdminRuntimeService] = None


async def get_admin_runtime_service() -> AdminRuntimeService:
    global _runtime_service_instance
    if _runtime_service_instance is None:
        _runtime_service_instance = AdminRuntimeService()
        await _runtime_service_instance.initialize()
    return _runtime_service_instance


@router.get("/status")
async def get_runtime_status(
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_RUNTIME_READ)),
    service: AdminRuntimeService = Depends(get_admin_runtime_service),
):
    """Get current runtime mode, maintenance state, and dependency health (admin read)."""
    return await service.get_status(operator_id=current_user.get("user_id"))


@router.get("/dependencies")
async def get_dependency_health(
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_RUNTIME_READ)),
    service: AdminRuntimeService = Depends(get_admin_runtime_service),
):
    """Get detailed dependency health for all probed services (admin read)."""
    deps = await service.get_dependency_health(operator_id=current_user.get("user_id"))
    return {"dependencies": [d.__dict__ for d in deps], "count": len(deps)}


@router.post("/check-health")
async def trigger_health_check(
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_RUNTIME_READ)),
    service: AdminRuntimeService = Depends(get_admin_runtime_service),
):
    """Trigger an immediate health check of all dependencies (admin read)."""
    return await service.trigger_health_check(operator_id=current_user.get("user_id"))


@router.post("/maintenance/enable")
async def enable_maintenance(
    request: EnableMaintenanceRequest,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_RUNTIME_MANAGE)),
    service: AdminRuntimeService = Depends(get_admin_runtime_service),
):
    """Enable maintenance mode (admin manage)."""
    eta = None
    if request.estimated_completion_time:
        try:
            eta = datetime.fromisoformat(request.estimated_completion_time)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid estimated_completion_time format. Use ISO 8601.",
            )

    success = await service.enable_maintenance(
        reason=request.reason,
        message=request.message,
        estimated_completion_time=eta,
        auto_end_policy=request.auto_end_policy,
        operator_id=current_user.get("user_id"),
        tenant_id=current_user.get("tenant_id"),
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to enable maintenance mode")
    return {"success": True, "mode": "maintenance", "reason": request.reason, "message": request.message}


@router.post("/maintenance/disable")
async def disable_maintenance(
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_RUNTIME_MANAGE)),
    service: AdminRuntimeService = Depends(get_admin_runtime_service),
):
    """Disable maintenance mode (admin manage)."""
    success = await service.disable_maintenance(
        operator_id=current_user.get("user_id"),
        tenant_id=current_user.get("tenant_id"),
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to disable maintenance mode")
    snapshot = await service.get_status(operator_id=current_user.get("user_id"))
    return {
        "success": True,
        "new_mode": snapshot.get("mode"),
        "normal_ready": snapshot.get("normal_ready"),
        "degraded_ready": snapshot.get("degraded_ready"),
    }


@router.put("/maintenance/update")
async def update_maintenance(
    request: UpdateMaintenanceRequest,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_RUNTIME_MANAGE)),
    service: AdminRuntimeService = Depends(get_admin_runtime_service),
):
    """Update the active maintenance window (admin manage)."""
    eta = None
    if request.estimated_completion_time:
        try:
            eta = datetime.fromisoformat(request.estimated_completion_time)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid ETA format")

    success = await service.update_maintenance(
        message=request.message,
        estimated_completion_time=eta,
        auto_end_policy=request.auto_end_policy,
        operator_id=current_user.get("user_id"),
        tenant_id=current_user.get("tenant_id"),
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update maintenance window")
    return {"success": True, "message": "Maintenance window updated"}


@router.get("/maintenance/notifications")
async def get_notification_subscriptions(
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_RUNTIME_READ)),
    service: AdminRuntimeService = Depends(get_admin_runtime_service),
    limit: int = 100,
):
    """View all maintenance notification subscriptions (admin read)."""
    subscriptions = await service.get_notification_subscriptions(
        limit=limit,
        operator_id=current_user.get("user_id"),
    )
    return {"subscriptions": subscriptions, "count": len(subscriptions)}


@router.post("/maintenance/notifications/subscribe")
async def subscribe_to_maintenance_notifications(
    channel: str = "in_app",
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_RUNTIME_READ)),
    service: AdminRuntimeService = Depends(get_admin_runtime_service),
):
    """Subscribe to receive notification when maintenance ends."""
    try:
        result = await service.get_notification_subscriptions(
            limit=1,
            operator_id=current_user.get("user_id"),
        )
        return {"success": True, "channel": channel, "status": "subscribed"}
    except Exception as exc:
        logger.error("Failed to subscribe to notifications: %s", exc)
        raise HTTPException(status_code=500, detail="Unable to subscribe")


@router.get("/events")
async def get_runtime_events(
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_RUNTIME_READ)),
    service: AdminRuntimeService = Depends(get_admin_runtime_service),
    limit: int = 50,
):
    """Get recent runtime events for audit trail (admin read)."""
    result = await service.get_runtime_events(
        limit=limit,
        operator_id=current_user.get("user_id"),
    )
    return result


@router.post("/cleanup")
async def run_data_cleanup(
    request: CleanupRequest,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_RUNTIME_MANAGE)),
):
    """Run data cleanup operations (admin manage)."""
    try:
        from ai_karen_engine.core.runtime.maintenance.data_cleanup_service import (
            get_data_cleanup_service,
        )
        cleanup_service = get_data_cleanup_service()
        report = await cleanup_service.run_cleanup(
            dry_run=request.dry_run,
            categories=request.categories,
        )
        return {
            "success": True,
            "dry_run": request.dry_run,
            "report": report.__dict__ if hasattr(report, "__dict__") else str(report),
        }
    except ImportError:
        raise HTTPException(status_code=501, detail="Data cleanup service not available")
    except Exception as exc:
        logger.error("Data cleanup failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(exc)}")
