from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ai_karen_engine.auth.rbac_middleware import (
    Permission,
    require_permission,
)
from ai_karen_engine.services.admin.admin_user_service import AdminUserService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/memory", tags=["admin-memory"])


class AdminMemoryStatsResponse(BaseModel):
    tenant_id: str
    total_items: int
    total_size_bytes: int
    last_cleanup: Optional[str] = None


class AdminMemoryCleanupRequest(BaseModel):
    tenant_id: str = "default"
    older_than_days: int = 30
    dry_run: bool = True


def get_admin_user_service() -> AdminUserService:
    from ai_karen_engine.auth.auth_service import get_auth_service
    return AdminUserService(auth_service=get_auth_service())


@router.get("/stats", response_model=List[AdminMemoryStatsResponse])
async def get_memory_stats(
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_MEMORY_READ)),
    tenant_id: Optional[str] = Query(None),
):
    """Get memory store statistics (admin read)."""
    effective_tenant = tenant_id or current_user.get("tenant_id", "default")
    try:
        from ai_karen_engine.database.client import MultiTenantPostgresClient
        db = MultiTenantPostgresClient()
        async with db.get_async_session() as session:
            from sqlalchemy import text
            result = await session.execute(
                text("SELECT COUNT(*) FROM memory_items WHERE tenant_id = :tid"),
                {"tid": effective_tenant},
            )
            total_items = result.scalar() or 0

            result = await session.execute(
                text("SELECT COALESCE(SUM(LENGTH(content)), 0) FROM memory_items WHERE tenant_id = :tid"),
                {"tid": effective_tenant},
            )
            total_size = result.scalar() or 0

        return [
            AdminMemoryStatsResponse(
                tenant_id=effective_tenant,
                total_items=total_items,
                total_size_bytes=total_size,
            )
        ]
    except Exception as exc:
        logger.error("Failed to get memory stats: %s", exc)
        return [AdminMemoryStatsResponse(tenant_id=effective_tenant, total_items=0, total_size_bytes=0)]


@router.get("/observability")
async def get_memory_observability(
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_MEMORY_READ)),
    tenant_id: Optional[str] = Query("default"),
):
    """Get memory observability data (admin read)."""
    try:
        from ai_karen_engine.database.client import MultiTenantPostgresClient
        db = MultiTenantPostgresClient()
        async with db.get_async_session() as session:
            from sqlalchemy import text
            result = await session.execute(
                text("SELECT COUNT(*) FROM memory_items WHERE tenant_id = :tid"),
                {"tid": tenant_id or "default"},
            )
            total_items = result.scalar() or 0

        return {
            "events": [],
            "summary": {
                "memory_used": total_items > 0,
                "total_items": total_items,
                "tenant_id": tenant_id or "default",
            },
        }
    except Exception as exc:
        logger.error("Failed to get memory observability: %s", exc)
        return {"events": [], "summary": {"memory_used": False}}


@router.post("/cleanup")
async def cleanup_memory(
    request: AdminMemoryCleanupRequest,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_MEMORY_MANAGE)),
):
    """Trigger memory cleanup (admin manage)."""
    try:
        from ai_karen_engine.core.runtime.maintenance.data_cleanup_service import (
            get_data_cleanup_service,
        )
        cleanup_service = get_data_cleanup_service()
        report = await cleanup_service.run_cleanup(
            dry_run=request.dry_run,
            categories=["memory"],
        )
        return {
            "success": True,
            "dry_run": request.dry_run,
            "report": report.__dict__ if hasattr(report, "__dict__") else str(report),
        }
    except ImportError:
        raise HTTPException(status_code=501, detail="Cleanup service not available")
    except Exception as exc:
        logger.error("Memory cleanup failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(exc)}")
