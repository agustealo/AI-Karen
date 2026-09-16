"""
Plugin Management API Routes - Production-ready plugin lifecycle endpoints.

Provides REST API for complete plugin lifecycle management including:
- Install/uninstall plugins
- Enable/disable plugins
- List plugins with status
- Backup and restore functionality
- Plugin marketplace integration
"""

import logging
from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ai_karen_engine.extensions.platform.core.plugin_lifecycle_manager import (
    PluginLifecycleManager,
    PluginLifecycleState,
    PluginOperation,
    PluginOperationResult,
)
from ai_karen_engine.extensions.platform.core.registry.plugin_registry import (
    PluginRegistry,
)
from ai_karen_engine.auth.rbac_middleware import Permission, require_permission
from ai_karen_engine.database.dependencies import get_async_db_session_dependency

logger = logging.getLogger("kari.plugin_api")

# Create router
router = APIRouter(prefix="/plugins", tags=["plugin-management"])


# Dependency to get plugin manager
async def get_plugin_manager(
    db_session: AsyncSession = Depends(get_async_db_session_dependency),
) -> PluginLifecycleManager:
    """Bind canonical lifecycle authority to the request-scoped async session."""
    from ai_karen_engine.extensions.platform.core.registry.plugin_registry import (
        get_registry,
    )

    return PluginLifecycleManager(
        registry=get_registry(),
        db_session=db_session,
    )


# Pydantic models for API
class PluginInfo(BaseModel):
    """Plugin information response model."""

    id: str
    name: str
    display_name: str
    description: Optional[str]
    version: str
    state: str
    installed_at: Optional[datetime]
    enabled: bool
    category: str
    capabilities: Dict[str, Any]


class PluginOperationRequest(BaseModel):
    """Plugin operation request model."""

    plugin_id: str = Field(..., description="Plugin identifier")
    source_url: Optional[str] = Field(None, description="Source URL for installation")
    version: Optional[str] = Field(None, description="Specific version to install")
    force: bool = Field(False, description="Force operation even if plugin exists")


class PluginOperationResponse(BaseModel):
    """Plugin operation response model."""

    success: bool
    plugin_id: str
    operation: str
    new_state: str
    message: str
    details: Dict[str, Any]
    timestamp: datetime
    duration_ms: int


class BackupInfo(BaseModel):
    """Backup information model."""

    plugin_id: str
    version: str
    backup_path: str
    created_at: datetime
    checksum: str
    size_bytes: int


# API Endpoints


@router.get("/", response_model=List[PluginInfo])
async def list_plugins(
    include_available: bool = Query(True, description="Include available plugins"),
    include_installed: bool = Query(True, description="Include installed plugins"),
    manager: PluginLifecycleManager = Depends(get_plugin_manager),
    current_user=Depends(require_permission(Permission.ADMIN_PLUGINS_READ)),
):
    """
    List all plugins with their current states.

    Returns both installed and available plugins based on query parameters.
    """
    try:
        plugins = await manager.list_plugins(
            include_available=include_available, include_installed=include_installed
        )

        return [
            PluginInfo(
                id=p["id"],
                name=p["name"],
                display_name=p["display_name"] or p["name"],
                description=p["description"],
                version=p["version"] or "unknown",
                state=p["state"].value
                if hasattr(p["state"], "value")
                else str(p["state"]),
                installed_at=p["installed_at"],
                enabled=p.get("enabled", False),
                category=p.get("category", "plugins"),
                capabilities=p.get("capabilities", {}),
            )
            for p in plugins
        ]
    except Exception as e:
        logger.error(f"Failed to list plugins: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list plugins: {str(e)}")


@router.get("/{plugin_id}", response_model=PluginInfo)
async def get_plugin_info(
    plugin_id: str,
    manager: PluginLifecycleManager = Depends(get_plugin_manager),
    current_user=Depends(require_permission(Permission.ADMIN_PLUGINS_READ)),
):
    """Get detailed information about a specific plugin."""
    try:
        plugins = await manager.list_plugins(
            include_available=True, include_installed=True
        )
        plugin = next((p for p in plugins if p["id"] == plugin_id), None)

        if not plugin:
            raise HTTPException(
                status_code=404, detail=f"Plugin '{plugin_id}' not found"
            )

        return PluginInfo(
            id=plugin["id"],
            name=plugin["name"],
            display_name=plugin["display_name"] or plugin["name"],
            description=plugin["description"],
            version=plugin["version"] or "unknown",
            state=plugin["state"].value
            if hasattr(plugin["state"], "value")
            else str(plugin["state"]),
            installed_at=plugin["installed_at"],
            enabled=plugin.get("enabled", False),
            category=plugin.get("category", "plugins"),
            capabilities=plugin.get("capabilities", {}),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get plugin info for {plugin_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to get plugin info: {str(e)}"
        )


@router.post("/install", response_model=PluginOperationResponse)
async def install_plugin(
    request: PluginOperationRequest,
    background_tasks: BackgroundTasks,
    manager: PluginLifecycleManager = Depends(get_plugin_manager),
    current_user=Depends(require_permission(Permission.ADMIN_PLUGINS_MANAGE)),
):
    """
    Install a plugin.

    Supports installation from local discovery or remote sources.
    """
    try:
        result = await manager.install_plugin(
            plugin_id=request.plugin_id,
            source_url=request.source_url,
            version=request.version,
            force=request.force,
        )

        return PluginOperationResponse(
            success=result.success,
            plugin_id=result.plugin_id,
            operation=result.operation.value,
            new_state=result.new_state.value,
            message=result.message,
            details=result.details,
            timestamp=result.timestamp,
            duration_ms=result.duration_ms,
        )
    except Exception as e:
        logger.error(
            f"Failed to install plugin {request.plugin_id}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Installation failed: {str(e)}")


@router.post("/{plugin_id}/uninstall", response_model=PluginOperationResponse)
async def uninstall_plugin(
    plugin_id: str,
    keep_backup: bool = Query(True, description="Keep backup after uninstallation"),
    manager: PluginLifecycleManager = Depends(get_plugin_manager),
    current_user=Depends(require_permission(Permission.ADMIN_PLUGINS_MANAGE)),
):
    """Uninstall a plugin completely."""
    try:
        result = await manager.uninstall_plugin(
            plugin_id=plugin_id, keep_backup=keep_backup
        )

        return PluginOperationResponse(
            success=result.success,
            plugin_id=result.plugin_id,
            operation=result.operation.value,
            new_state=result.new_state.value,
            message=result.message,
            details=result.details,
            timestamp=result.timestamp,
            duration_ms=result.duration_ms,
        )
    except Exception as e:
        logger.error(f"Failed to uninstall plugin {plugin_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Uninstallation failed: {str(e)}")


@router.post("/{plugin_id}/enable", response_model=PluginOperationResponse)
async def enable_plugin(
    plugin_id: str,
    manager: PluginLifecycleManager = Depends(get_plugin_manager),
    current_user=Depends(require_permission(Permission.ADMIN_PLUGINS_MANAGE)),
):
    """Enable a plugin (make it active)."""
    try:
        result = await manager.enable_plugin(plugin_id=plugin_id)

        return PluginOperationResponse(
            success=result.success,
            plugin_id=result.plugin_id,
            operation=result.operation.value,
            new_state=result.new_state.value,
            message=result.message,
            details=result.details,
            timestamp=result.timestamp,
            duration_ms=result.duration_ms,
        )
    except Exception as e:
        logger.error(f"Failed to enable plugin {plugin_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Enable failed: {str(e)}")


@router.post("/{plugin_id}/disable", response_model=PluginOperationResponse)
async def disable_plugin(
    plugin_id: str,
    manager: PluginLifecycleManager = Depends(get_plugin_manager),
    current_user=Depends(require_permission(Permission.ADMIN_PLUGINS_MANAGE)),
):
    """Disable a plugin (make it inactive)."""
    try:
        result = await manager.disable_plugin(plugin_id=plugin_id)

        return PluginOperationResponse(
            success=result.success,
            plugin_id=result.plugin_id,
            operation=result.operation.value,
            new_state=result.new_state.value,
            message=result.message,
            details=result.details,
            timestamp=result.timestamp,
            duration_ms=result.duration_ms,
        )
    except Exception as e:
        logger.error(f"Failed to disable plugin {plugin_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Disable failed: {str(e)}")


@router.post("/{plugin_id}/backup", response_model=BackupInfo)
async def create_plugin_backup(
    plugin_id: str,
    manager: PluginLifecycleManager = Depends(get_plugin_manager),
    current_user=Depends(require_permission(Permission.ADMIN_PLUGINS_MANAGE)),
):
    """Create a backup of an installed plugin."""
    try:
        backup = await manager.create_backup(plugin_id)
        if not backup:
            raise HTTPException(
                status_code=404,
                detail=f"Plugin '{plugin_id}' not found or not installed",
            )

        return BackupInfo(
            plugin_id=backup.plugin_id,
            version=backup.version,
            backup_path=str(backup.backup_path),
            created_at=backup.created_at,
            checksum=backup.checksum,
            size_bytes=backup.size_bytes,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to create backup for plugin {plugin_id}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Backup creation failed: {str(e)}")


@router.post("/{plugin_id}/restore", response_model=PluginOperationResponse)
async def restore_plugin_backup(
    plugin_id: str,
    backup_path: str = Query(..., description="Path to backup directory"),
    manager: PluginLifecycleManager = Depends(get_plugin_manager),
    current_user=Depends(require_permission(Permission.ADMIN_PLUGINS_MANAGE)),
):
    """Restore a plugin from backup."""
    try:
        backup_path_obj = Path(backup_path)
        if not backup_path_obj.exists():
            raise HTTPException(
                status_code=404, detail=f"Backup path does not exist: {backup_path}"
            )

        result = await manager.restore_backup(
            plugin_id=plugin_id, backup_path=backup_path_obj
        )

        return PluginOperationResponse(
            success=result.success,
            plugin_id=result.plugin_id,
            operation=result.operation.value,
            new_state=result.new_state.value,
            message=result.message,
            details=result.details,
            timestamp=result.timestamp,
            duration_ms=result.duration_ms,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to restore plugin {plugin_id} from {backup_path}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"Restore failed: {str(e)}")


@router.get("/backups/{plugin_id}", response_model=List[BackupInfo])
async def list_plugin_backups(
    plugin_id: str,
    manager: PluginLifecycleManager = Depends(get_plugin_manager),
    current_user=Depends(require_permission(Permission.ADMIN_PLUGINS_READ)),
):
    """List all available backups for a plugin."""
    try:
        # This would need to be implemented in the manager
        # For now, return empty list
        return []
    except Exception as e:
        logger.error(
            f"Failed to list backups for plugin {plugin_id}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Failed to list backups: {str(e)}")


@router.get("/marketplace", response_model=List[Dict[str, Any]])
async def get_marketplace_plugins(
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search query"),
    current_user=Depends(require_permission(Permission.ADMIN_PLUGINS_READ)),
):
    """
    Get available plugins from the marketplace.

    This endpoint would connect to a plugin marketplace/registry service.
    For now, returns available plugins from local discovery.
    """
    try:
        # This would connect to a marketplace service
        # For now, return local available plugins
        from ai_karen_engine.extensions.platform.core.registry.plugin_registry import (
            get_registry,
        )

        registry = get_registry()

        # Get discovered plugins
        discovered = await registry.discovery.discover_all()

        marketplace_plugins = []
        for metadata in discovered:
            if category and metadata.category != category:
                continue
            if (
                search
                and search.lower() not in (metadata.name + metadata.description).lower()
            ):
                continue

            marketplace_plugins.append(
                {
                    "id": metadata.name,
                    "name": metadata.name,
                    "display_name": metadata.display_name,
                    "description": metadata.description,
                    "version": metadata.version,
                    "category": metadata.category,
                    "capabilities": metadata.capabilities,
                    "source": "local",  # Would be "marketplace" for remote plugins
                    "download_url": None,  # Would be actual download URL
                    "author": metadata.author
                    if hasattr(metadata, "author")
                    else "Unknown",
                    "tags": getattr(metadata, "tags", []),
                    "rating": None,  # Would come from marketplace
                    "downloads": None,  # Would come from marketplace
                }
            )

        return marketplace_plugins
    except Exception as e:
        logger.error(f"Failed to get marketplace plugins: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to get marketplace plugins: {str(e)}"
        )


@router.get("/operations/history", response_model=List[Dict[str, Any]])
async def get_plugin_operation_history(
    plugin_id: Optional[str] = Query(None, description="Filter by plugin ID"),
    operation: Optional[str] = Query(None, description="Filter by operation type"),
    limit: int = Query(100, description="Maximum number of records to return"),
    manager: PluginLifecycleManager = Depends(get_plugin_manager),
    current_user=Depends(require_permission(Permission.ADMIN_PLUGINS_READ)),
):
    """Get plugin operation history."""
    try:
        # This would need to be implemented in the manager to query operation history
        # For now, return empty list
        return []
    except Exception as e:
        logger.error(f"Failed to get plugin operation history: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to get operation history: {str(e)}"
        )


@router.get("/health", response_model=Dict[str, Any])
async def get_plugin_system_health(
    manager: PluginLifecycleManager = Depends(get_plugin_manager),
):
    """Get overall plugin system health."""
    try:
        plugins = await manager.list_plugins()
        total_plugins = len(plugins)
        installed_plugins = len(
            [p for p in plugins if p["state"] != PluginLifecycleState.AVAILABLE]
        )
        enabled_plugins = len([p for p in plugins if p.get("enabled", False)])
        error_plugins = len(
            [p for p in plugins if p["state"] == PluginLifecycleState.ERROR]
        )

        health_status = "healthy"
        if error_plugins > 0:
            health_status = "degraded"
        if error_plugins > total_plugins * 0.5:  # More than 50% have errors
            health_status = "unhealthy"

        return {
            "status": health_status,
            "total_plugins": total_plugins,
            "installed_plugins": installed_plugins,
            "enabled_plugins": enabled_plugins,
            "error_plugins": error_plugins,
            "timestamp": datetime.now(),
        }
    except Exception as e:
        logger.error(f"Failed to get plugin system health: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now(),
        }
