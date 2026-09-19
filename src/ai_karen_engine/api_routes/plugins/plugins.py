"""Thin FastAPI ingress for the canonical plugin application service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.services.dependencies import (
    bypass_user_context_func,
    get_plugin_service,
)
from ai_karen_engine.services.audit.audit_logging import get_audit_logger
from ai_karen_engine.services.error_response_schemas import (
    WebAPIErrorCode,
    create_generic_error_response,
    create_service_error_response,
    get_http_status_for_error_code,
)
from ai_karen_engine.services.plugin_service import ExecutionStatus, PluginService

logger = get_logger(__name__)
router = APIRouter(
    tags=["plugins"],
    dependencies=[Depends(bypass_user_context_func)],
)
public_router = APIRouter(tags=["plugins-public"], prefix="/api/public/plugins")
_PLUGIN_MUTATION_PERMISSION = Permission.ADMIN_PLUGINS_MANAGE
_ENABLED_STATES = {"registered", "enabled", "loaded", "active"}


class ExecutePluginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plugin_name: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    timeout: int = Field(30, ge=1, le=300)
    session_id: Optional[str] = None


class ValidatePluginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plugin_name: str
    parameters: Dict[str, Any] = Field(default_factory=dict)


class PluginInfoResponse(BaseModel):
    name: str
    description: str
    version: str
    category: str
    status: str
    parameters: Dict[str, Any]
    author: str
    enabled: bool
    tags: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    last_executed: Optional[str] = None
    execution_count: int = 0
    success_rate: float = 0.0


class PluginExecutionResponse(BaseModel):
    success: bool
    result: Optional[Any] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    error: Optional[str] = None
    execution_time: float
    timestamp: str
    plugin_name: str
    session_id: Optional[str] = None


class PluginListResponse(BaseModel):
    plugins: List[PluginInfoResponse]
    total_count: int
    enabled_count: int
    disabled_count: int


class PluginMetricsResponse(BaseModel):
    total_plugins: int
    enabled_plugins: int
    total_executions: int
    successful_executions: int
    failed_executions: int
    average_execution_time: float
    plugins_by_category: Dict[str, int]
    most_used_plugins: List[Dict[str, Any]]
    recent_executions: List[Dict[str, Any]]


def _response_meta(request: Request) -> Dict[str, str]:
    correlation_id = (
        getattr(request.state, "correlation_id", None)
        or request.headers.get("X-Correlation-Id")
        or "unknown"
    )
    request_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-Id")
        or correlation_id
    )
    return {
        "request_id": str(request_id),
        "correlation_id": str(correlation_id),
    }


def _service_error(exc: Exception, user_message: str) -> HTTPException:
    response = create_service_error_response(
        service_name="plugin",
        error=exc,
        error_code=WebAPIErrorCode.PLUGIN_ERROR,
        user_message=user_message,
    )
    return HTTPException(
        status_code=get_http_status_for_error_code(WebAPIErrorCode.PLUGIN_ERROR),
        detail=response.model_dump(mode="json"),
    )


def _not_found(plugin_name: str) -> HTTPException:
    response = create_generic_error_response(
        error_code=WebAPIErrorCode.NOT_FOUND,
        message="Plugin not found",
        user_message="The requested plugin could not be found.",
        details={"plugin_name": plugin_name},
    )
    return HTTPException(
        status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
        detail=response.model_dump(mode="json"),
    )


def _manifest_parameters(manifest: Any) -> Dict[str, Any]:
    """Project only the schema explicitly declared by the manifest."""
    schema = getattr(manifest, "config_schema", None)
    if schema is None:
        return {}
    data = (
        schema.model_dump()
        if hasattr(schema, "model_dump")
        else schema
        if isinstance(schema, dict)
        else {}
    )
    properties = data.get("properties", {}) if isinstance(data, dict) else {}
    return dict(properties) if isinstance(properties, dict) else {}


def _manifest_dependencies(manifest: Any) -> List[str]:
    dependencies = getattr(manifest, "dependencies", None)
    if dependencies is None:
        return []
    raw = getattr(dependencies, "plugins", None)
    if raw is None and isinstance(dependencies, dict):
        raw = dependencies.get("plugins", [])
    return [str(value) for value in (raw or [])]


def _plugin_info_response(
    metadata: Dict[str, Any], plugin_service: PluginService
) -> PluginInfoResponse:
    manifest = metadata.get("manifest")
    state = str(
        getattr(metadata.get("status"), "value", metadata.get("status", "unknown"))
    )
    runtime = plugin_service.get_plugin_runtime_stats(
        str(getattr(manifest, "name", metadata.get("name", "unknown")))
    )
    if manifest is None:
        return PluginInfoResponse(
            name=str(metadata.get("name", "unknown")),
            description=str(metadata.get("description", "")),
            version=str(metadata.get("version", "")),
            category=str(metadata.get("category", "general")),
            status=state,
            parameters={},
            author=str(metadata.get("author", "")),
            enabled=state in _ENABLED_STATES,
            last_executed=runtime["last_executed"],
            execution_count=runtime["execution_count"],
            success_rate=runtime["success_rate"],
        )
    return PluginInfoResponse(
        name=manifest.name,
        description=manifest.description,
        version=manifest.version,
        category=manifest.category,
        status=state,
        parameters=_manifest_parameters(manifest),
        author=manifest.author,
        enabled=state in _ENABLED_STATES,
        tags=[str(tag) for tag in (getattr(manifest, "tags", []) or [])],
        dependencies=_manifest_dependencies(manifest),
        last_executed=runtime["last_executed"],
        execution_count=runtime["execution_count"],
        success_rate=runtime["success_rate"],
    )


def _permission_values(user: Dict[str, Any]) -> List[str]:
    rbac = get_rbac_manager()
    permissions = {item.value for item in rbac.get_user_permissions(user)}
    permissions.update(str(item) for item in (user.get("permissions", []) or []))
    return sorted(permissions)


def _audit_plugin_mutation(
    *,
    request: Request,
    user: Dict[str, Any],
    action: str,
    outcome: str,
    plugin_name: Optional[str] = None,
) -> None:
    meta = _response_meta(request)
    details: Dict[str, Any] = {
        "action": action,
        "outcome": outcome,
        "request_id": meta["request_id"],
    }
    if plugin_name:
        details["plugin_name"] = plugin_name
    get_audit_logger().log_audit_event(
        {
            "event_type": "plugin_runtime_mutation",
            "severity": "info" if outcome in {"attempt", "ok"} else "warning",
            "message": action,
            "user_id": user.get("user_id"),
            "tenant_id": user.get("tenant_id"),
            "correlation_id": meta["correlation_id"],
            "metadata": details,
        }
    )


def _require_plugin_mutation_access(
    request: Request,
    current_user: Dict[str, Any] = Depends(bypass_user_context_func),
) -> Dict[str, Any]:
    rbac = get_rbac_manager()
    granted = rbac.has_permission(current_user, _PLUGIN_MUTATION_PERMISSION)
    meta = _response_meta(request)
    rbac.audit_access_attempt(
        current_user,
        _PLUGIN_MUTATION_PERMISSION,
        resource=request.url.path,
        granted=granted,
        request=request,
        additional_context={
            "action": "manage_plugins",
            "request_id": meta["request_id"],
            "correlation_id": meta["correlation_id"],
        },
    )
    if not granted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Plugin management permission required",
        )
    return current_user


async def _execute(
    name: str,
    payload: ExecutePluginRequest,
    request: Request,
    user: Dict[str, Any],
    service: PluginService,
) -> PluginExecutionResponse:
    try:
        meta = _response_meta(request)
        result = await service.execute_plugin(
            plugin_name=name,
            parameters=payload.parameters,
            timeout_seconds=payload.timeout,
            user_id=str(user.get("user_id") or ""),
            tenant_id=str(user.get("tenant_id") or ""),
            session_id=payload.session_id,
            correlation_id=meta["correlation_id"],
            roles=[str(role) for role in (user.get("roles", []) or [])],
            permissions=_permission_values(user),
        )
        return PluginExecutionResponse(
            success=result.status is ExecutionStatus.COMPLETED,
            result=result.result,
            stdout=getattr(result, "stdout", None),
            stderr=getattr(result, "stderr", None),
            error=result.error,
            execution_time=result.execution_time,
            timestamp=(
                result.completed_at.astimezone(timezone.utc).isoformat()
                if result.completed_at
                else datetime.now(timezone.utc).isoformat()
            ),
            plugin_name=name,
            session_id=payload.session_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Plugin execution failed")
        raise _service_error(
            exc, "Failed to execute plugin. Please try again."
        ) from exc


@router.get("/", response_model=PluginListResponse)
async def list_plugins(
    category: Optional[str] = Query(None),
    enabled_only: bool = Query(False),
    plugin_service: PluginService = Depends(get_plugin_service),
):
    try:
        plugins = await plugin_service.list_plugins(category, enabled_only)
        responses = [
            _plugin_info_response(plugin, plugin_service) for plugin in plugins
        ]
        enabled = sum(item.enabled for item in responses)
        return PluginListResponse(
            plugins=responses,
            total_count=len(responses),
            enabled_count=enabled,
            disabled_count=len(responses) - enabled,
        )
    except Exception as exc:
        logger.exception("Failed to list plugins")
        raise _service_error(
            exc, "Failed to list plugins. Please try again."
        ) from exc


@router.post("/execute", response_model=PluginExecutionResponse)
async def execute_plugin_global(
    payload: ExecutePluginRequest,
    request: Request,
    current_user: Dict[str, Any] = Depends(bypass_user_context_func),
    plugin_service: PluginService = Depends(get_plugin_service),
):
    return await _execute(
        payload.plugin_name, payload, request, current_user, plugin_service
    )


@router.get("/categories")
async def get_plugin_categories(
    plugin_service: PluginService = Depends(get_plugin_service),
):
    try:
        counts: Dict[str, int] = {}
        for metadata in await plugin_service.list_plugins():
            manifest = metadata.get("manifest")
            category = str(
                getattr(manifest, "category", None)
                or metadata.get("category")
                or "general"
            )
            counts[category] = counts.get(category, 0) + 1
        categories = sorted(counts)
        return {
            "categories": categories,
            "category_counts": counts,
            "total_categories": len(categories),
        }
    except Exception as exc:
        logger.exception("Failed to get plugin categories")
        raise _service_error(
            exc, "Failed to get plugin categories. Please try again."
        ) from exc


@router.get("/metrics", response_model=PluginMetricsResponse)
async def get_plugin_metrics(
    plugin_service: PluginService = Depends(get_plugin_service),
):
    try:
        return PluginMetricsResponse(**await plugin_service.get_metrics())
    except Exception as exc:
        logger.exception("Failed to get plugin metrics")
        raise _service_error(
            exc, "Failed to get plugin metrics. Please try again."
        ) from exc


@router.post("/reload")
async def reload_plugins(
    request: Request,
    current_user: Dict[str, Any] = Depends(_require_plugin_mutation_access),
    plugin_service: PluginService = Depends(get_plugin_service),
):
    _audit_plugin_mutation(
        request=request,
        user=current_user,
        action="refresh_plugin_registry",
        outcome="attempt",
    )
    try:
        count = await plugin_service.refresh_plugins()
        _audit_plugin_mutation(
            request=request,
            user=current_user,
            action="refresh_plugin_registry",
            outcome="ok",
        )
        return {
            "success": True,
            "message": f"Refreshed {count} plugins successfully",
            "plugins_loaded": count,
        }
    except Exception as exc:
        logger.exception("Failed to refresh plugins")
        _audit_plugin_mutation(
            request=request,
            user=current_user,
            action="refresh_plugin_registry",
            outcome="error",
        )
        raise _service_error(
            exc, "Failed to refresh plugins. Please try again."
        ) from exc


@router.get("/health")
async def health_check(
    plugin_service: PluginService = Depends(get_plugin_service),
):
    try:
        return await plugin_service.health_check()
    except Exception as exc:
        logger.exception("Plugin health unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Plugin service health is unavailable",
        ) from exc


@router.get("/{plugin_name}", response_model=PluginInfoResponse)
async def get_plugin_info(
    plugin_name: str,
    plugin_service: PluginService = Depends(get_plugin_service),
):
    try:
        metadata = await plugin_service.get_plugin_info(plugin_name)
        if metadata is None:
            raise _not_found(plugin_name)
        return _plugin_info_response(metadata, plugin_service)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to get plugin info")
        raise _service_error(
            exc, "Failed to get plugin information. Please try again."
        ) from exc


@router.post("/{plugin_name}/execute", response_model=PluginExecutionResponse)
async def execute_plugin(
    plugin_name: str,
    payload: ExecutePluginRequest,
    request: Request,
    current_user: Dict[str, Any] = Depends(bypass_user_context_func),
    plugin_service: PluginService = Depends(get_plugin_service),
):
    if payload.plugin_name != plugin_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Plugin name in request body must match the route",
        )
    return await _execute(
        plugin_name, payload, request, current_user, plugin_service
    )


@router.post("/{plugin_name}/validate")
async def validate_plugin_parameters(
    plugin_name: str,
    payload: ValidatePluginRequest,
    plugin_service: PluginService = Depends(get_plugin_service),
):
    if payload.plugin_name != plugin_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Plugin name in request body must match the route",
        )
    if await plugin_service.get_plugin_info(plugin_name) is None:
        raise _not_found(plugin_name)
    valid = await plugin_service.validate_plugin_parameters(
        plugin_name, payload.parameters
    )
    return {
        "valid": valid,
        "plugin_name": plugin_name,
        "message": (
            "Parameters are valid"
            if valid
            else "Parameters do not satisfy the plugin manifest contract"
        ),
    }


async def _set_enabled(
    *,
    plugin_name: str,
    request: Request,
    user: Dict[str, Any],
    service: PluginService,
    enabled: bool,
) -> Dict[str, Any]:
    action = "enable_plugin" if enabled else "disable_plugin"
    _audit_plugin_mutation(
        request=request,
        user=user,
        action=action,
        outcome="attempt",
        plugin_name=plugin_name,
    )
    try:
        ok = (
            await service.enable_plugin(plugin_name)
            if enabled
            else await service.disable_plugin(plugin_name)
        )
        if not ok:
            raise _not_found(plugin_name)
        _audit_plugin_mutation(
            request=request,
            user=user,
            action=action,
            outcome="ok",
            plugin_name=plugin_name,
        )
        verb = "enabled" if enabled else "disabled"
        return {
            "success": True,
            "message": f"Plugin {plugin_name} {verb} successfully",
        }
    except HTTPException:
        _audit_plugin_mutation(
            request=request,
            user=user,
            action=action,
            outcome="rejected",
            plugin_name=plugin_name,
        )
        raise
    except Exception as exc:
        logger.exception("Plugin mutation failed")
        _audit_plugin_mutation(
            request=request,
            user=user,
            action=action,
            outcome="error",
            plugin_name=plugin_name,
        )
        raise _service_error(
            exc, "Failed to update plugin state. Please try again."
        ) from exc


@router.post("/{plugin_name}/enable")
async def enable_plugin(
    plugin_name: str,
    request: Request,
    current_user: Dict[str, Any] = Depends(_require_plugin_mutation_access),
    plugin_service: PluginService = Depends(get_plugin_service),
):
    return await _set_enabled(
        plugin_name=plugin_name,
        request=request,
        user=current_user,
        service=plugin_service,
        enabled=True,
    )


@router.post("/{plugin_name}/disable")
async def disable_plugin(
    plugin_name: str,
    request: Request,
    current_user: Dict[str, Any] = Depends(_require_plugin_mutation_access),
    plugin_service: PluginService = Depends(get_plugin_service),
):
    return await _set_enabled(
        plugin_name=plugin_name,
        request=request,
        user=current_user,
        service=plugin_service,
        enabled=False,
    )


@public_router.get("/", response_model=PluginListResponse)
async def list_plugins_public(
    category: Optional[str] = Query(None),
    enabled_only: bool = Query(False),
    plugin_service: PluginService = Depends(get_plugin_service),
):
    """Read-only public catalog mirror. Backend failure remains visible."""
    try:
        plugins = await plugin_service.list_plugins(category, enabled_only)
        responses = [
            _plugin_info_response(plugin, plugin_service) for plugin in plugins
        ]
        enabled = sum(item.enabled for item in responses)
        return PluginListResponse(
            plugins=responses,
            total_count=len(responses),
            enabled_count=enabled,
            disabled_count=len(responses) - enabled,
        )
    except Exception as exc:
        logger.exception("Public plugin catalog unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Plugin catalog is unavailable",
        ) from exc


__all__ = ["router", "public_router"]
