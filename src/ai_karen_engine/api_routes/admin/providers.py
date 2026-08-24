from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ai_karen_engine.auth.rbac_middleware import (
    Permission,
    require_permission,
)
from ai_karen_engine.services.admin.admin_provider_service import AdminProviderService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/providers", tags=["admin-providers"])


class AdminProviderListResponse(BaseModel):
    providers: List[Dict[str, Any]]
    total: int


class AdminProviderRegisterRequest(BaseModel):
    provider_id: str
    display_name: str
    base_url: str
    api_key_env: Optional[str] = None
    capabilities: List[str] = []
    default_model: Optional[str] = None
    metadata: Dict[str, Any] = {}


def get_admin_provider_service() -> AdminProviderService:
    return AdminProviderService()


@router.get("/", response_model=AdminProviderListResponse)
async def list_admin_providers(
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_PROVIDERS_READ)),
    category: Optional[str] = Query(None),
    available_only: bool = Query(False),
):
    """List all providers with backend truth (admin read)."""
    service = get_admin_provider_service()
    from ai_karen_engine.services.admin.admin_provider_service import AdminProviderFilter

    provider_filter = AdminProviderFilter(
        category=category,
        available_only=available_only,
    )
    providers = service.list_providers(
        provider_filter=provider_filter,
        operator_id=current_user.get("user_id"),
    )
    return AdminProviderListResponse(providers=providers, total=len(providers))


@router.get("/{provider_id}")
async def get_admin_provider(
    provider_id: str,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_PROVIDERS_READ)),
):
    """Get provider details with backend truth."""
    service = get_admin_provider_service()
    status = service.get_provider_status(
        provider_id,
        operator_id=current_user.get("user_id"),
    )
    if not status:
        raise HTTPException(status_code=404, detail="Provider not found")
    return {
        "provider_id": provider_id,
        "is_available": status.is_available,
        "health_status": status.health_status.value,
        "has_api_key": status.has_api_key,
        "capabilities": [c.value for c in status.capabilities],
        "last_check": status.last_check.isoformat() if status.last_check else None,
        "error_message": status.error_message,
    }


@router.get("/{provider_id}/models")
async def list_admin_provider_models(
    provider_id: str,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_PROVIDERS_READ)),
    healthy_only: bool = Query(True),
):
    """List registered models for a provider (admin read)."""
    service = get_admin_provider_service()
    models = service.get_registered_models(
        provider_id,
        healthy_only=healthy_only,
        operator_id=current_user.get("user_id"),
    )
    return {"provider_id": provider_id, "models": models, "count": len(models)}


@router.post("/{provider_id}/enable")
async def enable_admin_provider(
    provider_id: str,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_PROVIDERS_MANAGE)),
):
    """Enable a provider (admin manage)."""
    try:
        from ai_karen_engine.core.model_runtime.provider_registry_service import get_provider_registry_service
        registry = get_provider_registry_service()
        ok = registry.enable_provider(provider_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Provider not found")
        return {"success": True, "provider": provider_id, "enabled": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Enable provider failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{provider_id}/disable")
async def disable_admin_provider(
    provider_id: str,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_PROVIDERS_MANAGE)),
):
    """Disable a provider (admin manage)."""
    try:
        from ai_karen_engine.core.model_runtime.provider_registry_service import get_provider_registry_service
        registry = get_provider_registry_service()
        ok = registry.disable_provider(provider_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Provider not found")
        return {"success": True, "provider": provider_id, "disabled": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Disable provider failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/system/status")
async def get_admin_provider_system_status(
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_PROVIDERS_READ)),
):
    """Get overall provider system status (admin read)."""
    service = get_admin_provider_service()
    status = service.get_system_status(
        operator_id=current_user.get("user_id"),
    )
    return status
