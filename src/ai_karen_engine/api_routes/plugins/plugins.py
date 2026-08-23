"""FastAPI routes for Plugin service integration."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from pydantic import BaseModel, ConfigDict, Field

from ai_karen_engine.core.services.dependencies import (
    bypass_user_context_func,
    get_plugin_service,
)
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.services.error_response_schemas import (
    WebAPIErrorCode,
    create_generic_error_response,
    create_service_error_response,
    get_http_status_for_error_code,
)
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.plugin_service import PluginService
from ai_karen_engine.services.plugin_execution import ExecutionStatus

# REMOVED: RBAC access control - replaced with simple role checking
router = APIRouter(tags=["plugins"])
# Public mirror (read-only) for unauthenticated UI health checks
public_router = APIRouter(tags=["plugins-public"], prefix="/api/public/plugins")


logger = get_logger(__name__)


# Request/Response Models
class ExecutePluginRequest(BaseModel):
    """Request model for plugin execution."""

    plugin_name: str = Field(..., description="Name of plugin to execute")
    parameters: Dict[str, Any] = Field(
        default_factory=dict, description="Plugin parameters"
    )
    timeout: int = Field(30, ge=1, le=300, description="Execution timeout in seconds")
    session_id: Optional[str] = Field(None, description="Session ID")


class ValidatePluginRequest(BaseModel):
    """Request model for plugin validation."""

    plugin_name: str = Field(..., description="Name of plugin to validate")
    parameters: Dict[str, Any] = Field(
        default_factory=dict, description="Plugin parameters to validate"
    )


class PluginInfoResponse(BaseModel):
    """Response model for plugin information."""

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
    """Response model for plugin execution."""

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
    """Response model for plugin list."""

    plugins: List[PluginInfoResponse]
    total_count: int
    enabled_count: int
    disabled_count: int


class PluginMetricsResponse(BaseModel):
    """Response model for plugin metrics."""

    total_plugins: int
    enabled_plugins: int
    total_executions: int
    successful_executions: int
    failed_executions: int
    average_execution_time: float
    plugins_by_category: Dict[str, int]
    most_used_plugins: List[Dict[str, Any]]
    recent_executions: List[Dict[str, Any]]


# --- Helper Functions ---


async def _execute_plugin_logic(
    plugin_name: str,
    request: ExecutePluginRequest,
    plugin_service: PluginService,
) -> PluginExecutionResponse:
    """Helper to execute a plugin with given parameters."""
    try:
        # Execute the plugin
        result = await plugin_service.execute_plugin(
            plugin_name=plugin_name,
            parameters=request.parameters,
            timeout_seconds=request.timeout,
            session_id=request.session_id,
        )

        # Convert ExecutionResult.status to success boolean
        # ExecutionStatus.COMPLETED = "completed", other statuses indicate failure
        success = result.status.value == "completed"

        return PluginExecutionResponse(
            success=success,
            result=result.result,
            stdout=getattr(result, "stdout", None),
            stderr=getattr(result, "stderr", None),
            error=result.error,
            execution_time=result.execution_time,
            timestamp=result.completed_at.astimezone(timezone.utc).isoformat()
            if result.completed_at
            else datetime.now(timezone.utc).isoformat(),
            plugin_name=plugin_name,
            session_id=request.session_id,
        )

    except Exception as e:
        logger.exception(
            "Failed to execute plugin",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="plugin",
            error=e,
            error_code=WebAPIErrorCode.PLUGIN_ERROR,
            user_message="Failed to execute plugin. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(WebAPIErrorCode.PLUGIN_ERROR),
            detail=error_response.model_dump(mode="json"),
        )


# --- Global (Static) Routes ---


@router.get("/", response_model=PluginListResponse)
async def list_plugins(
    category: Optional[str] = Query(None, description="Filter by category"),
    enabled_only: bool = Query(False, description="Only return enabled plugins"),
    plugin_service: PluginService = Depends(get_plugin_service),
):
    """List all available plugins."""
    try:
        plugins = await plugin_service.list_plugins()

        # Apply filters
        if category:
            plugins = [p for p in plugins if p.category.lower() == category.lower()]

        if enabled_only:
            plugins = [p for p in plugins if p.enabled]

        # Convert to response format
        plugin_responses = []
        for plugin in plugins:
            plugin_responses.append(
                PluginInfoResponse(
                    name=plugin.name,
                    description=plugin.description,
                    version=plugin.version,
                    category=plugin.category,
                    status=plugin.status.value,
                    parameters=plugin.parameters,
                    author=plugin.author,
                    enabled=plugin.enabled,
                    tags=getattr(plugin, "tags", []),
                    dependencies=getattr(plugin, "dependencies", []),
                    last_executed=getattr(plugin, "last_executed", None),
                    execution_count=getattr(plugin, "execution_count", 0),
                    success_rate=getattr(plugin, "success_rate", 0.0),
                )
            )

        enabled_count = sum(1 for p in plugin_responses if p.enabled)
        disabled_count = len(plugin_responses) - enabled_count

        return PluginListResponse(
            plugins=plugin_responses,
            total_count=len(plugin_responses),
            enabled_count=enabled_count,
            disabled_count=disabled_count,
        )

    except Exception as e:
        logger.exception(
            "Failed to list plugins",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="plugin",
            error=e,
            error_code=WebAPIErrorCode.PLUGIN_ERROR,
            user_message="Failed to list plugins. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(WebAPIErrorCode.PLUGIN_ERROR),
            detail=error_response.model_dump(mode="json"),
        )


@router.post("/execute", response_model=PluginExecutionResponse)
async def execute_plugin_global(
    request: ExecutePluginRequest,
    plugin_service: PluginService = Depends(get_plugin_service),
):
    """Execute a plugin using the plugin name provided in the request body."""
    return await _execute_plugin_logic(request.plugin_name, request, plugin_service)


@router.get("/categories")
async def get_plugin_categories(
    plugin_service: PluginService = Depends(get_plugin_service),
):
    """Get list of plugin categories."""
    try:
        plugins = await plugin_service.list_plugins()
        categories = list(set(plugin.category for plugin in plugins))
        categories.sort()

        category_counts = {}
        for plugin in plugins:
            category_counts[plugin.category] = (
                category_counts.get(plugin.category, 0) + 1
            )

        return {
            "categories": categories,
            "category_counts": category_counts,
            "total_categories": len(categories),
        }

    except Exception as e:
        logger.exception(
            "Failed to get categories",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="plugin",
            error=e,
            error_code=WebAPIErrorCode.PLUGIN_ERROR,
            user_message="Failed to get plugin categories. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(WebAPIErrorCode.PLUGIN_ERROR),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/metrics", response_model=PluginMetricsResponse)
async def get_plugin_metrics(
    plugin_service: PluginService = Depends(get_plugin_service),
):
    """Get plugin execution metrics."""
    try:
        metrics = plugin_service.get_metrics()

        return PluginMetricsResponse(
            total_plugins=metrics.get("total_plugins", 0),
            enabled_plugins=metrics.get("enabled_plugins", 0),
            total_executions=metrics.get("total_executions", 0),
            successful_executions=metrics.get("successful_executions", 0),
            failed_executions=metrics.get("failed_executions", 0),
            average_execution_time=metrics.get("average_execution_time", 0.0),
            plugins_by_category=metrics.get("plugins_by_category", {}),
            most_used_plugins=metrics.get("most_used_plugins", []),
            recent_executions=metrics.get("recent_executions", []),
        )

    except Exception as e:
        logger.exception(
            "Failed to get metrics",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="plugin",
            error=e,
            error_code=WebAPIErrorCode.PLUGIN_ERROR,
            user_message="Failed to get plugin metrics. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(WebAPIErrorCode.PLUGIN_ERROR),
            detail=error_response.model_dump(mode="json"),
        )


@router.post("/reload")
async def reload_plugins(
    current_user: Dict[str, Any] = Depends(get_current_user),
    plugin_service: PluginService = Depends(get_plugin_service),
):
    """Reload all plugins from disk."""
    try:
        # Simple role checking - admin role required
        user_roles = current_user.get("roles", [])
        if "admin" not in user_roles:
            raise HTTPException(status_code=403, detail="Admin privileges required")

        count = await plugin_service.reload_plugins()
        return {
            "success": True,
            "message": f"Reloaded {count} plugins successfully",
            "plugins_loaded": count,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Failed to reload plugins",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="plugin",
            error=e,
            error_code=WebAPIErrorCode.PLUGIN_ERROR,
            user_message="Failed to reload plugins. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(WebAPIErrorCode.PLUGIN_ERROR),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/health")
async def health_check(plugin_service: PluginService = Depends(get_plugin_service)):
    """Health check for plugin service."""
    try:
        if hasattr(plugin_service, "health_check"):
            health_result = await plugin_service.health_check()
            return health_result
        else:
            return {
                "status": "healthy",
                "service": "plugin_service",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as e:
        logger.error(
            "Plugin service health check failed",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        return {
            "status": "unhealthy",
            "service": "plugin_service",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }


# --- Plugin-Specific Routes ---


@router.get("/{plugin_name}", response_model=PluginInfoResponse)
async def get_plugin_info(
    plugin_name: str, plugin_service: PluginService = Depends(get_plugin_service)
):
    """Get detailed information about a specific plugin."""
    try:
        plugin = await plugin_service.get_plugin_info(plugin_name)

        if not plugin:
            error_response = create_generic_error_response(
                error_code=WebAPIErrorCode.NOT_FOUND,
                message="Plugin not found",
                user_message="The requested plugin could not be found.",
                details={"plugin_name": plugin_name},
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
                detail=error_response.model_dump(mode="json"),
            )

        return PluginInfoResponse(
            name=plugin.name,
            description=plugin.description,
            version=plugin.version,
            category=plugin.category,
            status=plugin.status.value,
            parameters=plugin.parameters,
            author=plugin.author,
            enabled=plugin.enabled,
            tags=getattr(plugin, "tags", []),
            dependencies=getattr(plugin, "dependencies", []),
            last_executed=getattr(plugin, "last_executed", None),
            execution_count=getattr(plugin, "execution_count", 0),
            success_rate=getattr(plugin, "success_rate", 0.0),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Failed to get plugin info",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="plugin",
            error=e,
            error_code=WebAPIErrorCode.PLUGIN_ERROR,
            user_message="Failed to get plugin information. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(WebAPIErrorCode.PLUGIN_ERROR),
            detail=error_response.model_dump(mode="json"),
        )


@router.post("/{plugin_name}/execute", response_model=PluginExecutionResponse)
async def execute_plugin(
    plugin_name: str,
    request: ExecutePluginRequest,
    plugin_service: PluginService = Depends(get_plugin_service),
):
    """Execute a specific plugin with given parameters."""
    return await _execute_plugin_logic(plugin_name, request, plugin_service)


@router.post("/{plugin_name}/validate")
async def validate_plugin_parameters(
    plugin_name: str,
    request: ValidatePluginRequest,
    plugin_service: PluginService = Depends(get_plugin_service),
):
    """Validate plugin parameters."""
    try:
        is_valid = await plugin_service.validate_plugin(plugin_name, request.parameters)

        return {
            "valid": is_valid,
            "plugin_name": plugin_name,
            "message": "Parameters are valid" if is_valid else "Parameters are invalid",
        }

    except Exception as e:
        logger.exception(
            "Failed to validate plugin",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="plugin",
            error=e,
            error_code=WebAPIErrorCode.PLUGIN_ERROR,
            user_message="Failed to validate plugin parameters. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(WebAPIErrorCode.PLUGIN_ERROR),
            detail=error_response.model_dump(mode="json"),
        )


@router.post("/{plugin_name}/enable")
async def enable_plugin(
    plugin_name: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    plugin_service: PluginService = Depends(get_plugin_service),
):
    """Enable a plugin."""
    try:
        # Simple role checking - admin role required
        user_roles = current_user.get("roles", [])
        user_id = current_user.get("user_id", "unknown")
        logger.info(f"User roles for plugin enable: {user_roles}")
        logger.info(f"Current user data: {current_user}")

        # Check if user has admin role or is the default dev user
        if "admin" not in user_roles and user_id != "dev-user":
            raise HTTPException(status_code=403, detail="Admin privileges required")

        success = await plugin_service.enable_plugin(plugin_name)
        if not success:
            error_response = create_generic_error_response(
                error_code=WebAPIErrorCode.NOT_FOUND,
                message="Plugin not found",
                user_message="The requested plugin could not be found.",
                details={"plugin_name": plugin_name},
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
                detail=error_response.model_dump(mode="json"),
            )

        return {
            "success": True,
            "message": f"Plugin {plugin_name} enabled successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Failed to enable plugin",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="plugin",
            error=e,
            error_code=WebAPIErrorCode.PLUGIN_ERROR,
            user_message="Failed to enable plugin. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(WebAPIErrorCode.PLUGIN_ERROR),
            detail=error_response.model_dump(mode="json"),
        )


@router.post("/{plugin_name}/disable")
async def disable_plugin(
    plugin_name: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    plugin_service: PluginService = Depends(get_plugin_service),
):
    """Disable a plugin."""
    try:
        # Simple role checking - admin role required
        user_roles = current_user.get("roles", [])
        user_id = current_user.get("user_id", "unknown")
        if "admin" not in user_roles and user_id != "dev-user":
            raise HTTPException(status_code=403, detail="Admin privileges required")

        success = await plugin_service.disable_plugin(plugin_name)
        if not success:
            error_response = create_generic_error_response(
                error_code=WebAPIErrorCode.NOT_FOUND,
                message="Plugin not found",
                user_message="The requested plugin could not be found.",
                details={"plugin_name": plugin_name},
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
                detail=error_response.model_dump(mode="json"),
            )

        return {
            "success": True,
            "message": f"Plugin {plugin_name} disabled successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Failed to disable plugin",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="plugin",
            error=e,
            error_code=WebAPIErrorCode.PLUGIN_ERROR,
            user_message="Failed to disable plugin. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(WebAPIErrorCode.PLUGIN_ERROR),
            detail=error_response.model_dump(mode="json"),
        )


# --- Public (Mirror) Routes ---


@public_router.get("/", response_model=PluginListResponse)
async def list_plugins_public(
    category: Optional[str] = Query(None, description="Filter by category"),
    enabled_only: bool = Query(False, description="Only return enabled plugins"),
    plugin_service: PluginService = Depends(get_plugin_service),
):
    """Public, read-only plugin list for UI health checks.

    Mirrors list_plugins but does not require authentication.
    """
    try:
        return await list_plugins(category, enabled_only, plugin_service)  # type: ignore[arg-type]
    except Exception:
        # Never fail hard on public endpoint; return empty response
        return PluginListResponse(
            plugins=[], total_count=0, enabled_count=0, disabled_count=0
        )


__all__ = [
    "router",
    "public_router",
]
