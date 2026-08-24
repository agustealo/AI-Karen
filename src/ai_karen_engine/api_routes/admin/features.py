from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ai_karen_engine.auth.rbac_middleware import (
    Permission,
    require_permission,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/features", tags=["admin-features"])


class FeatureFlagResponse(BaseModel):
    key: str
    value: Any
    updated_at: Optional[str] = None


class FeatureFlagUpdateRequest(BaseModel):
    value: Any


_IN_MEMORY_FEATURES: Dict[str, Any] = {
    "maintenance_mode": False,
    "degraded_mode": False,
    "extension_system": True,
    "model_downloads": True,
    "training_pipeline": True,
    "plugin_marketplace": True,
    "audit_logging": True,
}


@router.get("/", response_model=List[FeatureFlagResponse])
async def list_feature_flags(
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_FEATURES_READ)),
):
    """List all feature flags (admin read)."""
    return [
        FeatureFlagResponse(
            key=key,
            value=value,
            updated_at=None,
        )
        for key, value in sorted(_IN_MEMORY_FEATURES.items())
    ]


@router.get("/{key}", response_model=FeatureFlagResponse)
async def get_feature_flag(
    key: str,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_FEATURES_READ)),
):
    """Get a single feature flag (admin read)."""
    if key not in _IN_MEMORY_FEATURES:
        raise HTTPException(status_code=404, detail="Feature flag not found")
    return FeatureFlagResponse(key=key, value=_IN_MEMORY_FEATURES[key])


@router.put("/{key}", response_model=FeatureFlagResponse)
async def update_feature_flag(
    key: str,
    request: FeatureFlagUpdateRequest,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_FEATURES_MANAGE)),
):
    """Update a feature flag (admin manage)."""
    if key not in _IN_MEMORY_FEATURES:
        raise HTTPException(status_code=404, detail="Feature flag not found")
    _IN_MEMORY_FEATURES[key] = request.value
    logger.info(
        "Feature flag %s updated to %s by %s",
        key,
        request.value,
        current_user.get("user_id"),
    )
    return FeatureFlagResponse(key=key, value=request.value)
