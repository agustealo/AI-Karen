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

router = APIRouter(prefix="/admin/plugins", tags=["admin-plugins"])


class AdminPluginListResponse(BaseModel):
    plugins: List[Dict[str, Any]]
    total: int


class AdminPluginToggleRequest(BaseModel):
    enabled: bool


def _get_plugin_registry():
    try:
        from ai_karen_engine.plugins.registry import PluginRegistry
        return PluginRegistry.get_instance()
    except Exception:
        return None


@router.get("/", response_model=AdminPluginListResponse)
async def list_admin_plugins(
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_PLUGINS_READ)),
):
    """List all plugins with governance status (admin read)."""
    registry = _get_plugin_registry()
    if not registry:
        return AdminPluginListResponse(plugins=[], total=0)

    plugins = []
    try:
        if hasattr(registry, "list_plugins"):
            for plugin in registry.list_plugins():
                plugins.append({
                    "id": getattr(plugin, "id", "unknown"),
                    "name": getattr(plugin, "name", "unknown"),
                    "version": getattr(plugin, "version", "unknown"),
                    "enabled": getattr(plugin, "enabled", False),
                    "category": getattr(plugin, "category", "unknown"),
                    "description": getattr(plugin, "description", ""),
                })
    except Exception as exc:
        logger.error("Failed to list plugins: %s", exc)

    return AdminPluginListResponse(plugins=plugins, total=len(plugins))


@router.post("/{plugin_id}/enable")
async def enable_admin_plugin(
    plugin_id: str,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_PLUGINS_MANAGE)),
):
    """Enable a plugin (admin manage)."""
    registry = _get_plugin_registry()
    if not registry:
        raise HTTPException(status_code=501, detail="Plugin registry not available")
    try:
        if hasattr(registry, "enable_plugin"):
            ok = registry.enable_plugin(plugin_id)
            if not ok:
                raise HTTPException(status_code=404, detail="Plugin not found")
        return {"success": True, "plugin": plugin_id, "enabled": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Enable plugin failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{plugin_id}/disable")
async def disable_admin_plugin(
    plugin_id: str,
    current_user: Dict[str, Any] = Depends(require_permission(Permission.ADMIN_PLUGINS_MANAGE)),
):
    """Disable a plugin (admin manage)."""
    registry = _get_plugin_registry()
    if not registry:
        raise HTTPException(status_code=501, detail="Plugin registry not available")
    try:
        if hasattr(registry, "disable_plugin"):
            ok = registry.disable_plugin(plugin_id)
            if not ok:
                raise HTTPException(status_code=404, detail="Plugin not found")
        return {"success": True, "plugin": plugin_id, "enabled": False}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Disable plugin failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
