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
from ai_karen_engine.services.admin.admin_tenant_service import AdminTenantService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


class AdminUserListResponse(BaseModel):
    users: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int


class AdminUserCreateRequest(BaseModel):
    email: str
    password: str
    full_name: str
    tenant_id: str = "default"
    roles: List[str] = []


class AdminUserUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    roles: Optional[List[str]] = None
    is_active: Optional[bool] = None
    is_verified: Optional[bool] = None


class AdminUserMetricsResponse(BaseModel):
    user_id: str
    hours: int
    event_count: int
    session_count: int
    total_session_minutes: float
    average_session_minutes: float
    last_seen: Optional[str] = None
    token_usage: Optional[int] = None
    token_usage_supported: bool = False


_auth_service_instance: Any = None


async def get_auth_service_instance():
    global _auth_service_instance
    if _auth_service_instance is None:
        from ai_karen_engine.auth.auth_service import get_auth_service
        _auth_service_instance = await get_auth_service()
    return _auth_service_instance


async def get_admin_user_service() -> AdminUserService:
    auth_service = await get_auth_service_instance()
    service = AdminUserService(auth_service=auth_service)
    await service.initialize()
    return service


@router.get("/", response_model=AdminUserListResponse)
async def list_admin_users(
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_USERS_READ)),
    service: AdminUserService = Depends(get_admin_user_service),
    tenant_id: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List users across tenants with admin filtering."""
    from ai_karen_engine.auth.auth_service import UserRole, UserStatus
    from ai_karen_engine.services.admin.admin_user_service import AdminUserFilter

    user_filter = AdminUserFilter(
        tenant_id=tenant_id,
        role=UserRole(role) if role else None,
        status=UserStatus(status) if status else None,
        search=search,
        limit=limit,
        offset=offset,
    )
    users = await service.list_users(
        user_filter=user_filter,
        operator_tenant_id=current_user.get("tenant_id"),
        operator_id=current_user.get("user_id"),
    )
    serialized = [
        {
            "user_id": str(u.id),
            "email": u.email,
            "full_name": u.full_name,
            "username": u.username,
            "tenant_id": str(u.tenant_id) if u.tenant_id else None,
            "roles": [r.value for r in u.roles],
            "status": u.status.value if hasattr(u.status, "value") else str(u.status),
            "is_active": u.is_active,
            "is_verified": u.is_verified,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "updated_at": u.updated_at.isoformat() if u.updated_at else None,
            "last_login": u.last_login.isoformat() if u.last_login else None,
        }
        for u in users
    ]
    return AdminUserListResponse(
        users=serialized,
        total=len(serialized),
        limit=limit,
        offset=offset,
    )


@router.post("/", status_code=201)
async def create_admin_user(
    request: AdminUserCreateRequest,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_USERS_MANAGE)),
    service: AdminUserService = Depends(get_admin_user_service),
):
    """Create a new user (admin only)."""
    from ai_karen_engine.auth.auth_service import UserRole

    user = await service.create_user(
        email=request.email,
        password=request.password,
        full_name=request.full_name,
        tenant_id=request.tenant_id,
        roles=[UserRole(r) for r in request.roles] if request.roles else None,
        operator_tenant_id=current_user.get("tenant_id"),
        operator_id=current_user.get("user_id"),
    )
    if not user:
        raise HTTPException(status_code=400, detail="Failed to create user")
    return {
        "user_id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "tenant_id": str(user.tenant_id) if user.tenant_id else None,
        "roles": [r.value for r in user.roles],
    }


@router.get("/{user_id}")
async def get_admin_user(
    user_id: str,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_USERS_READ)),
    service: AdminUserService = Depends(get_admin_user_service),
):
    """Get user details (admin only)."""
    user = await service.get_user(
        user_id,
        operator_tenant_id=current_user.get("tenant_id"),
        operator_id=current_user.get("user_id"),
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user_id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "username": user.username,
        "tenant_id": str(user.tenant_id) if user.tenant_id else None,
        "roles": [r.value for r in user.roles],
        "status": user.status.value if hasattr(user.status, "value") else str(user.status),
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        "last_login": user.last_login.isoformat() if user.last_login else None,
    }


@router.get("/{user_id}/metrics", response_model=AdminUserMetricsResponse)
async def get_admin_user_metrics(
    user_id: str,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_USERS_READ)),
    hours: int = 168,
):
    """Get backend-derived per-user metrics (admin read)."""
    from ai_karen_engine.core.services.dependencies import get_analytics_service
    analytics_service = get_analytics_service()
    try:
        metrics = analytics_service.get_user_metrics(user_id, hours=hours)
        return AdminUserMetricsResponse(**metrics)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to get user metrics")


@router.put("/{user_id}")
async def update_admin_user(
    user_id: str,
    request: AdminUserUpdateRequest,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_USERS_MANAGE)),
    service: AdminUserService = Depends(get_admin_user_service),
):
    """Update user details (admin only)."""
    updates = request.model_dump(exclude_none=True)
    success = await service.update_user(
        user_id,
        updates,
        operator_tenant_id=current_user.get("tenant_id"),
        operator_id=current_user.get("user_id"),
    )
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update user")
    return {"status": "success", "message": f"User {user_id} updated"}


@router.delete("/{user_id}", status_code=204)
async def delete_admin_user(
    user_id: str,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_USERS_MANAGE)),
    service: AdminUserService = Depends(get_admin_user_service),
):
    """Delete a user (admin only)."""
    if current_user.get("user_id") == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    success = await service.delete_user(
        user_id,
        operator_tenant_id=current_user.get("tenant_id"),
        operator_id=current_user.get("user_id"),
    )
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
    return None
