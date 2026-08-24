from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ai_karen_engine.auth.rbac_middleware import (
    Permission,
    require_permission,
)
from ai_karen_engine.core.services.dependencies import get_current_user
from ai_karen_engine.services.admin.admin_tenant_service import AdminTenantService
from ai_karen_engine.database.tenant_manager import TenantConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/tenants", tags=["admin-tenants"])


class AdminTenantListResponse(BaseModel):
    tenants: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int


class AdminTenantCreateRequest(BaseModel):
    name: str
    slug: str
    subscription_tier: str = "basic"
    admin_email: str
    settings: Dict[str, Any] = {}
    features: List[str] = []
    limits: Dict[str, int] = {}


class AdminTenantUpdateRequest(BaseModel):
    name: Optional[str] = None
    subscription_tier: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None
    features: Optional[List[str]] = None
    limits: Optional[Dict[str, int]] = None
    is_active: Optional[bool] = None


def get_admin_tenant_service() -> AdminTenantService:
    from ai_karen_engine.database.client import MultiTenantPostgresClient
    from ai_karen_engine.core.model_runtime.embedding_manager import get_embedding_manager
    db_client = MultiTenantPostgresClient()
    embedding_manager = get_embedding_manager()
    tenant_manager = TenantManager(db_client=db_client, embedding_manager=embedding_manager)
    return AdminTenantService(tenant_manager=tenant_manager)


@router.get("/", response_model=AdminTenantListResponse)
async def list_admin_tenants(
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_TENANTS_READ)),
    subscription_tier: Optional[str] = Query(None),
    active_only: bool = Query(True),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List tenants with admin filtering."""
    from ai_karen_engine.services.admin.admin_tenant_service import AdminTenantFilter

    service = get_admin_tenant_service()
    tenant_filter = AdminTenantFilter(
        subscription_tier=subscription_tier,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    tenants = await service.list_tenants(
        tenant_filter=tenant_filter,
        operator_id=current_user.get("user_id"),
    )
    serialized = [
        {
            "tenant_id": str(t.id),
            "name": t.name,
            "slug": t.slug,
            "subscription_tier": t.settings.get("subscription_tier", "basic"),
            "settings": t.settings,
            "is_active": t.is_active,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
        for t in tenants
    ]
    return AdminTenantListResponse(
        tenants=serialized,
        total=len(serialized),
        limit=limit,
        offset=offset,
    )


@router.post("/", status_code=201)
async def create_admin_tenant(
    request: AdminTenantCreateRequest,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_TENANTS_MANAGE)),
):
    """Create a new tenant with admin audit logging."""
    service = get_admin_tenant_service()
    config = TenantConfig(
        name=request.name,
        slug=request.slug,
        subscription_tier=request.subscription_tier,
        settings=request.settings,
        features=request.features,
        limits=request.limits,
    )
    tenant = await service.create_tenant(
        config=config,
        admin_email=request.admin_email,
        operator_id=current_user.get("user_id"),
    )
    if not tenant:
        raise HTTPException(status_code=400, detail="Failed to create tenant")
    return {
        "tenant_id": str(tenant.id),
        "name": tenant.name,
        "slug": tenant.slug,
        "subscription_tier": tenant.settings.get("subscription_tier", "basic"),
    }


@router.get("/{tenant_id}")
async def get_admin_tenant(
    tenant_id: str,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_TENANTS_READ)),
):
    """Get tenant details (admin only)."""
    service = get_admin_tenant_service()
    tenant = await service.get_tenant(
        tenant_id,
        operator_id=current_user.get("user_id"),
    )
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {
        "tenant_id": str(tenant.id),
        "name": tenant.name,
        "slug": tenant.slug,
        "subscription_tier": tenant.settings.get("subscription_tier", "basic"),
        "settings": tenant.settings,
        "is_active": tenant.is_active,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
        "updated_at": tenant.updated_at.isoformat() if tenant.updated_at else None,
    }


@router.get("/{tenant_id}/stats")
async def get_admin_tenant_stats(
    tenant_id: str,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_TENANTS_READ)),
):
    """Get tenant statistics (admin only)."""
    service = get_admin_tenant_service()
    stats = await service.get_tenant_stats(
        tenant_id,
        operator_id=current_user.get("user_id"),
    )
    if not stats:
        raise HTTPException(status_code=404, detail="Tenant stats not found")
    return stats.to_dict()


@router.put("/{tenant_id}")
async def update_admin_tenant(
    tenant_id: str,
    request: AdminTenantUpdateRequest,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_TENANTS_MANAGE)),
):
    """Update tenant details (admin only)."""
    service = get_admin_tenant_service()
    updates = request.model_dump(exclude_none=True)
    success = await service.update_tenant(
        tenant_id,
        updates,
        operator_id=current_user.get("user_id"),
    )
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update tenant")
    return {"status": "success", "message": f"Tenant {tenant_id} updated"}


@router.delete("/{tenant_id}", status_code=204)
async def delete_admin_tenant(
    tenant_id: str,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_TENANTS_MANAGE)),
):
    """Delete a tenant (admin only)."""
    service = get_admin_tenant_service()
    success = await service.delete_tenant(
        tenant_id,
        operator_id=current_user.get("user_id"),
    )
    if not success:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return None
