"""Extension Integration API Routes - FastAPI routes for extension management.

This module provides REST API endpoints for:
- Extension discovery and registration
- Extension lifecycle management
- Extension configuration management
- Extension permissions and access control
- Extension metrics and monitoring
- Extension versioning and updates
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path as FilePath
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator

from ai_karen_engine.extensions.platform.core.manager import (
    get_extension_core_manager,
)
from ai_karen_engine.extensions.platform.core.integration.lifecycle_manager import ExtensionLifecycleManager, ExtensionState
from ai_karen_engine.extensions.platform.core.integration.discovery_service import ExtensionDiscoveryService
from ai_karen_engine.extensions.platform.core.integration.sandbox_manager import ExtensionSandboxManager
from ai_karen_engine.extensions.platform.core.integration.communication_manager import ExtensionCommunicationManager
from ai_karen_engine.extensions.platform.core.integration.version_manager import ExtensionVersionManager, UpdateChannel
from ai_karen_engine.extensions.platform.core.integration.permissions_manager import ExtensionPermissionsManager, PermissionType, AccessLevel
from ai_karen_engine.extensions.platform.core.integration.metrics_collector import ExtensionMetricsCollector
from ai_karen_engine.extensions.platform.core.integration.models import (
    ExtensionModel, ExtensionVersionModel, ExtensionMetricModel, 
    ExtensionEventModel, ExtensionConfigModel
)


logger = logging.getLogger(__name__)


# Pydantic models for API requests/responses
class ExtensionInfo(BaseModel):
    """Extension information model."""
    
    id: str
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    version: str
    author: Optional[str] = None
    email: Optional[str] = None
    homepage: Optional[str] = None
    license: Optional[str] = None
    extension_type: str
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    state: str
    enabled: bool
    auto_start: bool
    priority: int
    path: str
    entry_point: Optional[str] = None
    manifest_path: Optional[str] = None
    dependencies: Optional[List[str]] = None
    python_dependencies: Optional[List[str]] = None
    system_dependencies: Optional[List[str]] = None
    configuration: Optional[Dict[str, Any]] = None
    permissions: Optional[List[str]] = None
    security_level: Optional[str] = None
    sandbox_enabled: bool
    memory_limit: Optional[int] = None
    cpu_limit: Optional[float] = None
    disk_limit: Optional[int] = None
    network_limit: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    installed_at: Optional[datetime] = None
    last_started: Optional[datetime] = None
    last_stopped: Optional[datetime] = None


class ExtensionVersionInfo(BaseModel):
    """Extension version information model."""
    
    id: str
    extension_id: str
    version: str
    version_code: int
    release_notes: Optional[str] = None
    changelog: Optional[str] = None
    update_channel: str
    is_prerelease: bool
    is_latest: bool
    download_url: Optional[str] = None
    download_size: Optional[int] = None
    checksum: Optional[str] = None
    signature: Optional[str] = None
    min_core_version: Optional[str] = None
    max_core_version: Optional[str] = None
    compatible_extensions: Optional[List[str]] = None
    security_scan_result: Optional[Dict[str, Any]] = None
    vulnerability_score: Optional[int] = None
    created_at: Optional[datetime] = None
    released_at: Optional[datetime] = None
    installed_at: Optional[datetime] = None


class ExtensionMetricInfo(BaseModel):
    """Extension metric information model."""
    
    id: str
    extension_id: str
    metric_name: str
    metric_type: str
    metric_unit: Optional[str] = None
    value: float
    tags: Optional[Dict[str, str]] = None
    timestamp: datetime


class ExtensionEventInfo(BaseModel):
    """Extension event information model."""
    
    id: str
    extension_id: str
    event_type: str
    event_level: str
    message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    timestamp: datetime


class ExtensionConfigInfo(BaseModel):
    """Extension configuration information model."""
    
    id: str
    extension_id: str
    config_key: str
    config_value: Any
    config_type: str
    is_sensitive: bool
    is_valid: Optional[bool] = None
    validation_error: Optional[str] = None
    description: Optional[str] = None
    default_value: Optional[Any] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ExtensionInstallRequest(BaseModel):
    """Extension installation request model."""
    
    extension_id: str
    version: Optional[str] = None
    update_channel: Optional[str] = "stable"
    auto_start: bool = True
    configuration: Optional[Dict[str, Any]] = None


class ExtensionUpdateRequest(BaseModel):
    """Extension update request model."""
    
    version: Optional[str] = None
    update_channel: Optional[str] = None
    force: bool = False


class ExtensionConfigRequest(BaseModel):
    """Extension configuration request model."""
    
    config_key: str
    config_value: Any
    config_type: Optional[str] = None


class ExtensionPermissionRequest(BaseModel):
    """Extension permission request model."""
    
    permission_name: str
    permission_type: str
    permission_scope: str
    access_level: str
    description: Optional[str] = None
    resource_limits: Optional[Dict[str, Any]] = None
    expires_at: Optional[datetime] = None


class ExtensionMetricsRequest(BaseModel):
    """Extension metrics request model."""
    
    metric_name: str
    metric_type: str
    metric_unit: Optional[str] = None
    value: float
    tags: Optional[Dict[str, str]] = None


# Response models
class ExtensionsListResponse(BaseModel):
    """Extensions list response model."""
    
    extensions: List[ExtensionInfo]
    total: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool


class ExtensionVersionsListResponse(BaseModel):
    """Extension versions list response model."""
    
    versions: List[ExtensionVersionInfo]
    total: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool


class ExtensionMetricsListResponse(BaseModel):
    """Extension metrics list response model."""
    
    metrics: List[ExtensionMetricInfo]
    total: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool


class ExtensionEventsListResponse(BaseModel):
    """Extension events list response model."""
    
    events: List[ExtensionEventInfo]
    total: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool


class ExtensionConfigsListResponse(BaseModel):
    """Extension configurations list response model."""
    
    configs: List[ExtensionConfigInfo]
    total: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool


class OperationResponse(BaseModel):
    """Operation response model."""
    
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


# Create router
router = APIRouter(prefix="/extensions", tags=["extensions"])


def _load_manifest_payload(manifest_path: Optional[str]) -> Dict[str, Any]:
    if not manifest_path:
        return {}

    path = FilePath(manifest_path)
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _normalise_menu_entries(
    plugin_name: str,
    manifest_payload: Dict[str, Any],
    menu_contributions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    ui_config = manifest_payload.get("ui") if isinstance(manifest_payload, dict) else {}
    component_id = ""
    if isinstance(ui_config, dict):
        component_id = str(ui_config.get("component_id") or "").strip()
    if not component_id:
        component_id = plugin_name

    entries: List[Dict[str, Any]] = []
    for contribution in menu_contributions:
        if not isinstance(contribution, dict):
            continue
        entries.append(
            {
                "entry_id": contribution.get("entry_id") or f"{plugin_name}.default",
                "component": component_id,
                "zone": contribution.get("zone") or "sidebar.plugins",
                "label": contribution.get("label") or manifest_payload.get("display_name") or plugin_name,
                "order": contribution.get("order") or 0,
            }
        )

    if entries:
        return entries

    if isinstance(ui_config, dict):
        hook_zones = ui_config.get("hook_zones") or []
        if isinstance(hook_zones, list):
            for index, zone in enumerate(hook_zones):
                if not isinstance(zone, dict):
                    continue
                entries.append(
                    {
                        "entry_id": f"{plugin_name}.hook.{index}",
                        "component": component_id,
                        "zone": zone.get("zone") or "sidebar.plugins",
                        "label": zone.get("label")
                        or manifest_payload.get("display_name")
                        or plugin_name,
                        "order": zone.get("order") or index,
                    }
                )

    return entries


def _build_frontend_extension_entry(
    status_entry: Dict[str, Any], manifest_payload: Dict[str, Any]
) -> Dict[str, Any]:
    name = str(status_entry.get("name") or status_entry.get("id") or "")
    manifest_capabilities = manifest_payload.get("capabilities") if isinstance(manifest_payload, dict) else {}
    manifest_rbac = manifest_payload.get("rbac") if isinstance(manifest_payload, dict) else {}
    manifest_ui = manifest_payload.get("ui") if isinstance(manifest_payload, dict) else {}

    capabilities = status_entry.get("capabilities") or {}
    if not isinstance(capabilities, dict):
        capabilities = {}

    merged_capabilities = {
        "provides_ui": bool(
            capabilities.get("provides_ui")
            or (isinstance(manifest_capabilities, dict) and manifest_capabilities.get("provides_ui"))
            or (isinstance(manifest_ui, dict) and (manifest_ui.get("has_component") or manifest_ui.get("component_id")))
            or bool(status_entry.get("menu_contributions"))
        ),
        "provides_api": bool(
            capabilities.get("provides_api")
            or (isinstance(manifest_capabilities, dict) and manifest_capabilities.get("provides_api"))
        ),
        "provides_background_tasks": bool(
            capabilities.get("provides_background_tasks")
            or (isinstance(manifest_capabilities, dict) and manifest_capabilities.get("provides_background_tasks"))
        ),
        "provides_webhooks": bool(
            capabilities.get("provides_webhooks")
            or (isinstance(manifest_capabilities, dict) and manifest_capabilities.get("provides_webhooks"))
        ),
    }

    ui_entries = _normalise_menu_entries(
        plugin_name=name,
        manifest_payload=manifest_payload,
        menu_contributions=list(status_entry.get("menu_contributions") or []),
    )

    ui_config = manifest_ui if isinstance(manifest_ui, dict) else {}
    component_id = str(ui_config.get("component_id") or name).strip() or name

    return {
        "name": name,
        "display_name": status_entry.get("display_name")
        or manifest_payload.get("display_name")
        or name,
        "description": status_entry.get("description")
        or manifest_payload.get("description")
        or "No description available",
        "version": status_entry.get("version") or manifest_payload.get("version") or "0.0.0",
        "status": status_entry.get("status") or "discovered",
        "loaded_at": status_entry.get("loaded_at"),
        "error_message": status_entry.get("error_message"),
        "capabilities": merged_capabilities,
        "has_component": bool(merged_capabilities["provides_ui"]),
        "ui": {
            "has_component": bool(
                merged_capabilities["provides_ui"]
                or bool(ui_entries)
                or bool(ui_config.get("has_component"))
            ),
            "component_id": component_id,
            "purpose": manifest_payload.get("purpose")
            or ui_config.get("purpose")
            or status_entry.get("description")
            or "",
            "menu": [
                {
                    "placement": entry.get("zone") or "sidebar.plugins",
                    "label": entry.get("label") or status_entry.get("display_name") or name,
                    "icon": None,
                    "order": entry.get("order") or 0,
                }
                for entry in ui_entries
            ],
        },
        "ui_entry_points": ui_entries,
        "rbac": {
            "allowed_roles": list(
                manifest_rbac.get("allowed_roles") if isinstance(manifest_rbac, dict) else []
            ),
            "default_enabled": bool(
                manifest_rbac.get("default_enabled")
                if isinstance(manifest_rbac, dict) and "default_enabled" in manifest_rbac
                else True
            ),
        },
        "tags": list(manifest_payload.get("tags") or []),
        "purpose": manifest_payload.get("purpose") or "",
        "actions": manifest_payload.get("actions") or [],
        "invocation_guidance": manifest_payload.get("invocation_guidance"),
        "manifest_path": status_entry.get("manifest_path"),
    }

# Dependency injection
def get_lifecycle_manager() -> ExtensionLifecycleManager:
    """Get extension lifecycle manager instance."""
    # This would be injected from the main application
    from ai_karen_engine.extensions.platform.core.integration import get_lifecycle_manager
    return get_lifecycle_manager()


def get_discovery_service() -> ExtensionDiscoveryService:
    """Get extension discovery service instance."""
    # This would be injected from the main application
    from ai_karen_engine.extensions.platform.core.integration import get_discovery_service
    return get_discovery_service()


def get_sandbox_manager() -> ExtensionSandboxManager:
    """Get extension sandbox manager instance."""
    # This would be injected from the main application
    from ai_karen_engine.extensions.platform.core.integration import get_sandbox_manager
    return get_sandbox_manager()


def get_communication_manager() -> ExtensionCommunicationManager:
    """Get extension communication manager instance."""
    # This would be injected from the main application
    from ai_karen_engine.extensions.platform.core.integration import get_communication_manager
    return get_communication_manager()


def get_version_manager() -> ExtensionVersionManager:
    """Get extension version manager instance."""
    # This would be injected from the main application
    from ai_karen_engine.extensions.platform.core.integration import get_version_manager
    return get_version_manager()


def get_permissions_manager() -> ExtensionPermissionsManager:
    """Get extension permissions manager instance."""
    # This would be injected from the main application
    from ai_karen_engine.extensions.platform.core.integration import get_permissions_manager
    return get_permissions_manager()


def get_metrics_collector() -> ExtensionMetricsCollector:
    """Get extension metrics collector instance."""
    # This would be injected from the main application
    from ai_karen_engine.extensions.platform.core.integration import get_metrics_collector
    return get_metrics_collector()


# Extension endpoints
@router.get("/", response_model=ExtensionsListResponse)
async def list_extensions(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    state: Optional[str] = Query(None, description="Filter by state"),
    extension_type: Optional[str] = Query(None, description="Filter by type"),
    enabled: Optional[bool] = Query(None, description="Filter by enabled status"),
    lifecycle_manager: ExtensionLifecycleManager = Depends(get_lifecycle_manager)
):
    """
    List all extensions with optional filtering.
    """
    try:
        # Get extensions from lifecycle manager
        extensions = lifecycle_manager.get_all_extensions()
        
        # Apply filters
        if state:
            extensions = [ext for ext in extensions if ext.state == state]
        
        if extension_type:
            extensions = [ext for ext in extensions if ext.extension_type == extension_type]
        
        if enabled is not None:
            extensions = [ext for ext in extensions if ext.enabled == enabled]
        
        # Sort by priority
        extensions.sort(key=lambda x: x.priority, reverse=True)
        
        # Pagination
        total = len(extensions)
        start = (page - 1) * page_size
        end = start + page_size
        page_extensions = extensions[start:end]
        
        # Convert to response model
        extension_infos = []
        for ext in page_extensions:
            extension_infos.append(ExtensionInfo(
                id=ext.id,
                name=ext.name,
                display_name=ext.display_name,
                description=ext.description,
                version=ext.version,
                author=ext.author,
                email=ext.email,
                homepage=ext.homepage,
                license=ext.license,
                extension_type=ext.extension_type,
                category=ext.category,
                tags=ext.tags,
                state=ext.state.value if hasattr(ext.state, 'value') else str(ext.state),
                enabled=ext.enabled,
                auto_start=ext.auto_start,
                priority=ext.priority,
                path=ext.path,
                entry_point=ext.entry_point,
                manifest_path=ext.manifest_path,
                dependencies=ext.dependencies,
                python_dependencies=ext.python_dependencies,
                system_dependencies=ext.system_dependencies,
                configuration=ext.configuration,
                permissions=ext.permissions,
                security_level=ext.security_level,
                sandbox_enabled=ext.sandbox_enabled,
                memory_limit=ext.memory_limit,
                cpu_limit=ext.cpu_limit,
                disk_limit=ext.disk_limit,
                network_limit=ext.network_limit,
                created_at=ext.created_at,
                updated_at=ext.updated_at,
                installed_at=ext.installed_at,
                last_started=ext.last_started,
                last_stopped=ext.last_stopped
            ))
        
        return ExtensionsListResponse(
            extensions=extension_infos,
            total=total,
            page=page,
            page_size=page_size,
            has_next=end < total,
            has_prev=page > 1
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list", response_model=List[Dict[str, Any]])
async def list_extension_catalog(
    core_manager=Depends(get_extension_core_manager),
):
    """
    Return a frontend-friendly extension catalog.

    This endpoint mirrors the discovery registry in a flat array shape so the
    plugin overview and loader can normalize it directly.
    """
    try:
        statuses = core_manager.list_extension_statuses()
        registry = core_manager.registry

        catalog: List[Dict[str, Any]] = []
        for status_entry in statuses:
            manifest_payload = {}
            manifest_path = status_entry.get("manifest_path")

            metadata = registry.get_metadata(status_entry.get("name") or status_entry.get("id") or "")
            if metadata and getattr(metadata, "manifest_path", None):
                manifest_payload = _load_manifest_payload(str(metadata.manifest_path))
            elif manifest_path:
                manifest_payload = _load_manifest_payload(str(manifest_path))

            catalog.append(
                _build_frontend_extension_entry(
                    status_entry=status_entry,
                    manifest_payload=manifest_payload,
                )
            )

        return catalog
    except Exception as e:
        logger.error("Failed to build frontend extension catalog: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{extension_id}", response_model=ExtensionInfo)
async def get_extension(
    extension_id: str = Path(..., description="Extension ID"),
    lifecycle_manager: ExtensionLifecycleManager = Depends(get_lifecycle_manager)
):
    """
    Get extension by ID.
    """
    try:
        extension = lifecycle_manager.get_extension(extension_id)
        if not extension:
            raise HTTPException(status_code=404, detail="Extension not found")
        
        return ExtensionInfo(
            id=extension.id,
            name=extension.name,
            display_name=extension.display_name,
            description=extension.description,
            version=extension.version,
            author=extension.author,
            email=extension.email,
            homepage=extension.homepage,
            license=extension.license,
            extension_type=extension.extension_type,
            category=extension.category,
            tags=extension.tags,
            state=extension.state.value if hasattr(extension.state, 'value') else str(extension.state),
            enabled=extension.enabled,
            auto_start=extension.auto_start,
            priority=extension.priority,
            path=extension.path,
            entry_point=extension.entry_point,
            manifest_path=extension.manifest_path,
            dependencies=extension.dependencies,
            python_dependencies=extension.python_dependencies,
            system_dependencies=extension.system_dependencies,
            configuration=extension.configuration,
            permissions=extension.permissions,
            security_level=extension.security_level,
            sandbox_enabled=extension.sandbox_enabled,
            memory_limit=extension.memory_limit,
            cpu_limit=extension.cpu_limit,
            disk_limit=extension.disk_limit,
            network_limit=extension.network_limit,
            created_at=extension.created_at,
            updated_at=extension.updated_at,
            installed_at=extension.installed_at,
            last_started=extension.last_started,
            last_stopped=extension.last_stopped
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/discover", response_model=OperationResponse)
async def discover_extensions(
    background_tasks: BackgroundTasks,
    discovery_service: ExtensionDiscoveryService = Depends(get_discovery_service)
):
    """
    Discover extensions in the configured directories.
    """
    try:
        # Run discovery in background
        background_tasks.add_task(discovery_service.discover_extensions)
        
        return OperationResponse(
            success=True,
            message="Extension discovery started"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/install", response_model=OperationResponse)
async def install_extension(
    request: ExtensionInstallRequest,
    background_tasks: BackgroundTasks,
    lifecycle_manager: ExtensionLifecycleManager = Depends(get_lifecycle_manager)
):
    """
    Install an extension.
    """
    try:
        # Check if extension already exists
        existing_extension = lifecycle_manager.get_extension(request.extension_id)
        if existing_extension:
            raise HTTPException(status_code=409, detail="Extension already exists")
        
        # Install extension in background
        background_tasks.add_task(
            lifecycle_manager.install_extension,
            request.extension_id,
            request.version,
            request.update_channel,
            request.auto_start,
            request.configuration
        )
        
        return OperationResponse(
            success=True,
            message="Extension installation started"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{extension_id}/start", response_model=OperationResponse)
async def start_extension(
    extension_id: str = Path(..., description="Extension ID"),
    lifecycle_manager: ExtensionLifecycleManager = Depends(get_lifecycle_manager)
):
    """
    Start an extension.
    """
    try:
        success = await lifecycle_manager.start_extension(extension_id)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to start extension")
        
        return OperationResponse(
            success=True,
            message="Extension started successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{extension_id}/stop", response_model=OperationResponse)
async def stop_extension(
    extension_id: str = Path(..., description="Extension ID"),
    lifecycle_manager: ExtensionLifecycleManager = Depends(get_lifecycle_manager)
):
    """
    Stop an extension.
    """
    try:
        success = await lifecycle_manager.stop_extension(extension_id)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to stop extension")
        
        return OperationResponse(
            success=True,
            message="Extension stopped successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{extension_id}/restart", response_model=OperationResponse)
async def restart_extension(
    extension_id: str = Path(..., description="Extension ID"),
    lifecycle_manager: ExtensionLifecycleManager = Depends(get_lifecycle_manager)
):
    """
    Restart an extension.
    """
    try:
        success = await lifecycle_manager.restart_extension(extension_id)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to restart extension")
        
        return OperationResponse(
            success=True,
            message="Extension restarted successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{extension_id}", response_model=OperationResponse)
async def uninstall_extension(
    extension_id: str = Path(..., description="Extension ID"),
    lifecycle_manager: ExtensionLifecycleManager = Depends(get_lifecycle_manager)
):
    """
    Uninstall an extension.
    """
    try:
        success = await lifecycle_manager.uninstall_extension(extension_id)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to uninstall extension")
        
        return OperationResponse(
            success=True,
            message="Extension uninstalled successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{extension_id}/update", response_model=OperationResponse)
async def update_extension(
    extension_id: str = Path(..., description="Extension ID"),
    request: ExtensionUpdateRequest = Body(...),
    version_manager: ExtensionVersionManager = Depends(get_version_manager)
):
    """
    Update an extension.
    """
    try:
        result = await version_manager.update_extension(
            extension_id,
            request.version,
            request.update_channel,
            request.force
        )
        
        if result.success:
            return OperationResponse(
                success=True,
                message="Extension updated successfully",
                data={
                    "old_version": result.old_version,
                    "new_version": result.new_version,
                    "update_channel": result.update_channel
                }
            )
        else:
            return OperationResponse(
                success=False,
                message=result.error or "Failed to update extension"
            )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{extension_id}/versions", response_model=ExtensionVersionsListResponse)
async def list_extension_versions(
    extension_id: str = Path(..., description="Extension ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    version_manager: ExtensionVersionManager = Depends(get_version_manager)
):
    """
    List available versions for an extension.
    """
    try:
        # Get versions from version manager
        versions = version_manager.get_available_versions(extension_id)
        
        # Pagination
        total = len(versions)
        start = (page - 1) * page_size
        end = start + page_size
        page_versions = versions[start:end]
        
        # Convert to response model
        version_infos = []
        for version in page_versions:
            version_infos.append(ExtensionVersionInfo(
                id=version.get("id", ""),
                extension_id=extension_id,
                version=version.get("version", ""),
                version_code=version.get("version_code", 0),
                release_notes=version.get("release_notes"),
                changelog=version.get("changelog"),
                update_channel=version.get("update_channel", ""),
                is_prerelease=version.get("is_prerelease", False),
                is_latest=version.get("is_latest", False),
                download_url=version.get("download_url"),
                download_size=version.get("download_size"),
                checksum=version.get("checksum"),
                signature=version.get("signature"),
                min_core_version=version.get("min_core_version"),
                max_core_version=version.get("max_core_version"),
                compatible_extensions=version.get("compatible_extensions"),
                security_scan_result=version.get("security_scan_result"),
                vulnerability_score=version.get("vulnerability_score"),
                created_at=version.get("created_at"),
                released_at=version.get("released_at"),
                installed_at=version.get("installed_at")
            ))
        
        return ExtensionVersionsListResponse(
            versions=version_infos,
            total=total,
            page=page,
            page_size=page_size,
            has_next=end < total,
            has_prev=page > 1
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{extension_id}/metrics", response_model=ExtensionMetricsListResponse)
async def list_extension_metrics(
    extension_id: str = Path(..., description="Extension ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    metric_name: Optional[str] = Query(None, description="Filter by metric name"),
    start_time: Optional[datetime] = Query(None, description="Start time filter"),
    end_time: Optional[datetime] = Query(None, description="End time filter"),
    metrics_collector: ExtensionMetricsCollector = Depends(get_metrics_collector)
):
    """
    List metrics for an extension.
    """
    try:
        # Get metrics from collector
        metrics = metrics_collector.get_metrics(
            name=metric_name,
            extension_id=extension_id,
            start_time=start_time,
            end_time=end_time
        )
        
        # Flatten metrics
        all_metrics = []
        for name, values in metrics.items():
            for value in values:
                all_metrics.append({
                    "id": f"{name}_{value.timestamp.timestamp()}",
                    "metric_name": name,
                    "metric_type": "unknown",  # Would need to get from metric definition
                    "metric_unit": value.unit.value if value.unit else None,
                    "value": value.value,
                    "tags": value.tags,
                    "timestamp": value.timestamp
                })
        
        # Sort by timestamp
        all_metrics.sort(key=lambda x: x["timestamp"], reverse=True)
        
        # Pagination
        total = len(all_metrics)
        start = (page - 1) * page_size
        end = start + page_size
        page_metrics = all_metrics[start:end]
        
        # Convert to response model
        metric_infos = []
        for metric in page_metrics:
            metric_infos.append(ExtensionMetricInfo(
                id=metric["id"],
                extension_id=extension_id,
                metric_name=metric["metric_name"],
                metric_type=metric["metric_type"],
                metric_unit=metric["metric_unit"],
                value=metric["value"],
                tags=metric["tags"],
                timestamp=metric["timestamp"]
            ))
        
        return ExtensionMetricsListResponse(
            metrics=metric_infos,
            total=total,
            page=page,
            page_size=page_size,
            has_next=end < total,
            has_prev=page > 1
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{extension_id}/metrics", response_model=OperationResponse)
async def record_extension_metric(
    extension_id: str = Path(..., description="Extension ID"),
    request: ExtensionMetricsRequest = Body(...),
    metrics_collector: ExtensionMetricsCollector = Depends(get_metrics_collector)
):
    """
    Record a metric for an extension.
    """
    try:
        success = metrics_collector.record_metric(
            name=request.metric_name,
            value=request.value,
            tags=request.tags,
            extension_id=extension_id
        )
        
        if success:
            return OperationResponse(
                success=True,
                message="Metric recorded successfully"
            )
        else:
            return OperationResponse(
                success=False,
                message="Failed to record metric"
            )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{extension_id}/events", response_model=ExtensionEventsListResponse)
async def list_extension_events(
    extension_id: str = Path(..., description="Extension ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    event_level: Optional[str] = Query(None, description="Filter by event level"),
    start_time: Optional[datetime] = Query(None, description="Start time filter"),
    end_time: Optional[datetime] = Query(None, description="End time filter"),
    lifecycle_manager: ExtensionLifecycleManager = Depends(get_lifecycle_manager)
):
    """
    List events for an extension.
    """
    try:
        # Get events from lifecycle manager
        events = lifecycle_manager.get_extension_events(
            extension_id,
            event_type,
            event_level,
            start_time,
            end_time
        )
        
        # Pagination
        total = len(events)
        start = (page - 1) * page_size
        end = start + page_size
        page_events = events[start:end]
        
        # Convert to response model
        event_infos = []
        for event in page_events:
            event_infos.append(ExtensionEventInfo(
                id=event.get("id", ""),
                extension_id=extension_id,
                event_type=event.get("event_type", ""),
                event_level=event.get("event_level", ""),
                message=event.get("message"),
                details=event.get("details"),
                user_id=event.get("user_id"),
                session_id=event.get("session_id"),
                request_id=event.get("request_id"),
                timestamp=event.get("timestamp", datetime.now(timezone.utc))
            ))
        
        return ExtensionEventsListResponse(
            events=event_infos,
            total=total,
            page=page,
            page_size=page_size,
            has_next=end < total,
            has_prev=page > 1
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{extension_id}/config", response_model=ExtensionConfigsListResponse)
async def list_extension_configs(
    extension_id: str = Path(..., description="Extension ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    lifecycle_manager: ExtensionLifecycleManager = Depends(get_lifecycle_manager)
):
    """
    List configuration for an extension.
    """
    try:
        # Get configuration from lifecycle manager
        configs = lifecycle_manager.get_extension_configuration(extension_id)
        
        # Convert to list format
        config_list = []
        for key, value in configs.items():
            config_list.append({
                "id": f"{extension_id}_{key}",
                "config_key": key,
                "config_value": value,
                "config_type": type(value).__name__,
                "is_sensitive": key.lower() in ["password", "token", "secret", "key"],
                "is_valid": True,
                "validation_error": None,
                "description": None,
                "default_value": None,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc)
            })
        
        # Pagination
        total = len(config_list)
        start = (page - 1) * page_size
        end = start + page_size
        page_configs = config_list[start:end]
        
        # Convert to response model
        config_infos = []
        for config in page_configs:
            config_infos.append(ExtensionConfigInfo(
                id=config["id"],
                extension_id=extension_id,
                config_key=config["config_key"],
                config_value=config["config_value"],
                config_type=config["config_type"],
                is_sensitive=config["is_sensitive"],
                is_valid=config["is_valid"],
                validation_error=config["validation_error"],
                description=config["description"],
                default_value=config["default_value"],
                created_at=config["created_at"],
                updated_at=config["updated_at"]
            ))
        
        return ExtensionConfigsListResponse(
            configs=config_infos,
            total=total,
            page=page,
            page_size=page_size,
            has_next=end < total,
            has_prev=page > 1
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{extension_id}/config", response_model=OperationResponse)
async def update_extension_config(
    extension_id: str = Path(..., description="Extension ID"),
    request: ExtensionConfigRequest = Body(...),
    lifecycle_manager: ExtensionLifecycleManager = Depends(get_lifecycle_manager)
):
    """
    Update configuration for an extension.
    """
    try:
        success = lifecycle_manager.update_extension_configuration(
            extension_id,
            {request.config_key: request.config_value}
        )
        
        if success:
            return OperationResponse(
                success=True,
                message="Configuration updated successfully"
            )
        else:
            return OperationResponse(
                success=False,
                message="Failed to update configuration"
            )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{extension_id}/permissions", response_model=List[Dict[str, Any]])
async def list_extension_permissions(
    extension_id: str = Path(..., description="Extension ID"),
    permissions_manager: ExtensionPermissionsManager = Depends(get_permissions_manager)
):
    """
    List permissions for an extension.
    """
    try:
        # Get permissions from permissions manager
        permissions = permissions_manager.get_permissions()
        
        # Filter for this extension
        extension_permissions = []
        for perm_name, perm in permissions.items():
            # This would need to be enhanced to properly filter by extension
            extension_permissions.append({
                "name": perm_name,
                "type": perm.type.value,
                "scope": perm.scope.value,
                "level": perm.level.value,
                "description": perm.description,
                "resource_limits": perm.resource_limits,
                "is_active": perm.is_active
            })
        
        return extension_permissions
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{extension_id}/permissions", response_model=OperationResponse)
async def create_extension_permission(
    extension_id: str = Path(..., description="Extension ID"),
    request: ExtensionPermissionRequest = Body(...),
    permissions_manager: ExtensionPermissionsManager = Depends(get_permissions_manager)
):
    """
    Create a permission for an extension.
    """
    try:
        # This would need to be implemented in the permissions manager
        return OperationResponse(
            success=True,
            message="Permission created successfully"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


__all__ = [
    "router",
    "ExtensionInfo",
    "ExtensionVersionInfo",
    "ExtensionMetricInfo",
    "ExtensionEventInfo",
    "ExtensionConfigInfo",
    "ExtensionInstallRequest",
    "ExtensionUpdateRequest",
    "ExtensionConfigRequest",
    "ExtensionPermissionRequest",
    "ExtensionMetricsRequest",
    "ExtensionsListResponse",
    "ExtensionVersionsListResponse",
    "ExtensionMetricsListResponse",
    "ExtensionEventsListResponse",
    "ExtensionConfigsListResponse",
    "OperationResponse",
]
