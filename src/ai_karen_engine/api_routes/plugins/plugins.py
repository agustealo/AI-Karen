"""Thin FastAPI ingress for the canonical plugin application service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager
from ai_karen_engine.auth.session import get_plugin_lifecycle_context
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.persistence.repositories.plugin_lifecycle_repository import (
    PluginLifecycleApprovalRejected, PluginLifecycleRevisionConflict,
)
from ai_karen_engine.services.approvals import (
    ApprovalNotFoundError, ApprovalScopeError, ApprovalStateError,
)
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
from ai_karen_engine.extensions.plugin_kernel import PluginKernel
from ai_karen_engine.services.plugin_service import ExecutionStatus, PluginService

logger = get_logger(__name__)
router = APIRouter(
    tags=["plugins"],
    dependencies=[Depends(bypass_user_context_func)],
)
public_router = APIRouter(tags=["plugins-public"], prefix="/api/public/plugins")
_PLUGIN_MUTATION_PERMISSION = Permission.ADMIN_PLUGINS_MANAGE
_ENABLED_STATES = {"registered", "enabled", "loaded", "active"}


class LifecycleApprovalExecutionRequest(BaseModel):
    """Only receipt ID is accepted; lifecycle scope never comes from HTTP."""

    model_config = ConfigDict(extra="forbid")
    approval_id: UUID


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


class FileExplorerInventoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    parent_id: None = None
    kind: Literal["file"]
    name: str
    revision: str
    size_bytes: int
    sha256: str


class FileExplorerInventoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: List[FileExplorerInventoryEntry]
    has_more: bool
    next_cursor: Optional[str] = None
    inventory_semantics: Literal["owner_metadata_page_not_live_acl"]
    request_id: str
    correlation_id: str


class FileExplorerFolderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder_id: UUID
    parent_folder_id: Optional[UUID]
    name: str = Field(min_length=1, max_length=256)
    revision: str = Field(pattern=r"^[1-9][0-9]{0,18}$")


class FileExplorerHierarchyFileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: UUID
    parent_id: Optional[UUID]
    kind: Literal["file"]
    name: str
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    organization_revision: str = Field(pattern=r"^[1-9][0-9]{0,18}$")


class FileExplorerHierarchyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    available: bool
    folders: List[FileExplorerFolderResponse]
    breadcrumbs: List[FileExplorerFolderResponse]
    has_more: bool
    next_folder_id: Optional[UUID] = None
    files: List[FileExplorerHierarchyFileResponse]
    files_has_more: bool
    next_file_cursor: Optional[str] = None
    request_id: str
    correlation_id: str


class ContentSourceReference(BaseModel):
    """A selection receipt is not a permission grant."""

    model_config = ConfigDict(extra="forbid")
    source_id: UUID
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class ContentOwnerSourcesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["analyze", "search", "compare"]
    references: List[ContentSourceReference] = Field(min_length=1, max_length=12)
    query: Optional[str] = Field(default=None, min_length=1, max_length=512)
    left_id: Optional[UUID] = None
    right_id: Optional[UUID] = None


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
    """Expose action parameter definitions, never stored configuration fields."""
    schema = PluginKernel.execution_input_schema(manifest)
    properties = schema.get("properties", {})
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
            "severity": "info" if outcome in {"attempt", "ok", "pending", "verified_committed"} else "warning",
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


@router.get("/search/articles/{article_id}")
async def get_search_article(
    article_id: str,
    current_user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Read a saved search article, bound exclusively to the authenticated principal."""
    user_id = str(current_user.get("user_id") or "").strip()
    tenant_id = str(current_user.get("tenant_id") or "").strip()
    if not user_id or not tenant_id or tenant_id == "default":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated tenant and user required",
        )

    from ai_karen_engine.services.database.repositories.repository_factory import (
        get_runtime_search_article_service,
    )

    service = get_runtime_search_article_service()
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored article retrieval is unavailable",
        )
    try:
        document = await service.read(
            tenant_id=tenant_id, user_id=user_id, article_id=article_id
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="Article access denied")
    except (RuntimeError, UnicodeDecodeError) as exc:
        logger.warning("Stored article retrieval failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored article retrieval is unavailable",
        )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found",
        )
    return {"article_id": article_id, "full_content": document}


def _file_explorer_read_scope(request: Request, current_user: Dict[str, Any], operation: str):
    user_id = str(current_user.get("user_id") or "").strip()
    tenant_id = str(current_user.get("tenant_id") or "").strip()
    if not user_id or not tenant_id or tenant_id in {"default", "dev-tenant"}:
        raise HTTPException(status_code=401, detail="Authenticated user and tenant required")

    rbac = get_rbac_manager()
    permitted = rbac.has_permission(current_user, Permission.DATA_READ)
    meta = _response_meta(request)
    rbac.audit_access_attempt(
        current_user,
        Permission.DATA_READ,
        resource=request.url.path,
        granted=permitted,
        request=request,
        additional_context={
            "operation": operation,
            "request_id": meta["request_id"],
            "correlation_id": meta["correlation_id"],
        },
    )
    if not permitted:
        raise HTTPException(status_code=403, detail="File inventory read access denied")

    return tenant_id, user_id, meta


@router.get("/file-explorer/inventory", response_model=FileExplorerInventoryResponse)
async def list_file_explorer_inventory(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    cursor: Optional[str] = Query(None, min_length=1, max_length=768),
    current_user: Dict[str, Any] = Depends(bypass_user_context_func),
    plugin_service: PluginService = Depends(get_plugin_service),
) -> FileExplorerInventoryResponse:
    """Thin authenticated ingress; RuntimePolicy and PluginKernel execute the read."""
    tenant_id, user_id, meta = _file_explorer_read_scope(
        request, current_user, "file_explorer_owner_inventory",
    )
    try:
        page = await plugin_service.list_file_explorer_owner_page(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=[str(role) for role in (current_user.get("roles", []) or [])],
            permissions=_permission_values(current_user),
            request_id=meta["request_id"],
            correlation_id=meta["correlation_id"],
            limit=limit,
            cursor=cursor,
        )
        return FileExplorerInventoryResponse.model_validate(page)
    except PermissionError:
        raise HTTPException(status_code=403, detail="File inventory access denied") from None
    except ValueError:
        raise HTTPException(status_code=422, detail="File inventory request invalid") from None
    except Exception as exc:
        logger.warning(
            "file_explorer_owner_inventory_unavailable",
            extra={
                "request_id": meta["request_id"],
                "correlation_id": meta["correlation_id"],
                "tenant_id": tenant_id,
                "user_id": user_id,
                "error_type": type(exc).__name__,
            },
        )
        raise HTTPException(
            status_code=503, detail="File inventory is unavailable"
        ) from None


@router.get("/file-explorer/hierarchy", response_model=FileExplorerHierarchyResponse)
async def list_file_explorer_hierarchy(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    parent_folder_id: Optional[UUID] = None,
    after_folder_id: Optional[UUID] = None,
    file_cursor: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(bypass_user_context_func),
    plugin_service: PluginService = Depends(get_plugin_service),
) -> FileExplorerHierarchyResponse:
    tenant_id, user_id, meta = _file_explorer_read_scope(
        request, current_user, "file_explorer_owner_hierarchy",
    )
    try:
        if file_cursor is not None and not 1 <= len(file_cursor) <= 768:
            raise ValueError("file_explorer_cursor_invalid")
        page = await plugin_service.list_file_explorer_owner_page(
            user_id=user_id, tenant_id=tenant_id,
            roles=[str(role) for role in (current_user.get("roles", []) or [])],
            permissions=_permission_values(current_user),
            request_id=meta["request_id"], correlation_id=meta["correlation_id"],
            limit=limit, hierarchy=True,
            parent_folder_id=str(parent_folder_id) if parent_folder_id else None,
            after_folder_id=str(after_folder_id) if after_folder_id else None,
            file_cursor=file_cursor,
        )
        return FileExplorerHierarchyResponse.model_validate(page)
    except PermissionError:
        raise HTTPException(status_code=403, detail="File hierarchy access denied") from None
    except ValueError:
        raise HTTPException(status_code=422, detail="File hierarchy request invalid") from None
    except Exception:
        logger.warning("file_explorer_hierarchy_unavailable", extra=meta)
        raise HTTPException(status_code=503, detail="File hierarchy unavailable") from None


@router.get("/content-intelligence/inventory", response_model=FileExplorerInventoryResponse)
async def list_content_inventory(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    cursor: Optional[str] = Query(None, min_length=1, max_length=768),
    current_user: Dict[str, Any] = Depends(bypass_user_context_func),
    plugin_service: PluginService = Depends(get_plugin_service),
) -> FileExplorerInventoryResponse:
    """Thin authenticated ingress; RuntimePolicy and PluginKernel execute the read."""
    user_id = str(current_user.get("user_id") or "").strip()
    tenant_id = str(current_user.get("tenant_id") or "").strip()
    try:
        if str(UUID(user_id)) != user_id or str(UUID(tenant_id)) != tenant_id:
            raise ValueError("unscoped")
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(status_code=401, detail="Authenticated user and tenant required") from None

    rbac = get_rbac_manager()
    permitted = rbac.has_permission(current_user, Permission.DATA_READ)
    meta = _response_meta(request)
    rbac.audit_access_attempt(
        current_user,
        Permission.DATA_READ,
        resource=request.url.path,
        granted=permitted,
        request=request,
        additional_context={
            "operation": "content_owner_inventory",
            "request_id": meta["request_id"],
            "correlation_id": meta["correlation_id"],
        },
    )
    if not permitted:
        raise HTTPException(status_code=403, detail="Content inventory read access denied")

    try:
        page = await plugin_service.list_content_owner_page(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=[str(role) for role in (current_user.get("roles", []) or [])],
            permissions=_permission_values(current_user),
            request_id=meta["request_id"],
            correlation_id=meta["correlation_id"],
            limit=limit,
            cursor=cursor,
        )
        return FileExplorerInventoryResponse.model_validate(page)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Content inventory access denied") from None
    except ValueError:
        raise HTTPException(status_code=422, detail="Content inventory request invalid") from None
    except Exception as exc:
        logger.warning(
            "content_owner_inventory_unavailable",
            extra={
                "request_id": meta["request_id"],
                "correlation_id": meta["correlation_id"],
                "tenant_id": tenant_id,
                "user_id": user_id,
                "error_type": type(exc).__name__,
            },
        )
        raise HTTPException(
            status_code=503, detail="Content inventory is unavailable"
        ) from None


@router.post("/content-intelligence/owner-sources")
async def analyze_content_owner_sources(
    payload: ContentOwnerSourcesRequest,
    request: Request,
    current_user: Dict[str, Any] = Depends(bypass_user_context_func),
    plugin_service: PluginService = Depends(get_plugin_service),
) -> Dict[str, Any]:
    """Thin ingress: source reads and execution require runtime admission."""
    user_id = str(current_user.get("user_id") or "").strip()
    tenant_id = str(current_user.get("tenant_id") or "").strip()
    try:
        if str(UUID(user_id)) != user_id or str(UUID(tenant_id)) != tenant_id:
            raise ValueError("unscoped")
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(status_code=401, detail="Authenticated user and tenant required") from None

    rbac = get_rbac_manager()
    permitted = rbac.has_permission(current_user, Permission.DATA_READ)
    meta = _response_meta(request)
    rbac.audit_access_attempt(
        current_user,
        Permission.DATA_READ,
        resource=request.url.path,
        granted=permitted,
        request=request,
        additional_context={
            "operation": "content_owner_sources",
            "request_id": meta["request_id"],
            "correlation_id": meta["correlation_id"],
        },
    )
    if not permitted:
        raise HTTPException(status_code=403, detail="Content source access denied")

    try:
        return await plugin_service.analyze_content_owner_sources(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=[str(role) for role in (current_user.get("roles", []) or [])],
            permissions=_permission_values(current_user),
            request_id=meta["request_id"],
            correlation_id=meta["correlation_id"],
            operation=payload.operation,
            references=[
                {"source_id": str(item.source_id), "revision": item.revision}
                for item in payload.references
            ],
            query=payload.query,
            left_id=str(payload.left_id) if payload.left_id is not None else None,
            right_id=str(payload.right_id) if payload.right_id is not None else None,
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="Content source access denied") from None
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid content source request") from None
    except Exception as exc:
        logger.warning(
            "content_source_execution_unavailable",
            extra={
                "request_id": meta["request_id"],
                "correlation_id": meta["correlation_id"],
                "tenant_id": tenant_id,
                "user_id": user_id,
                "error_type": type(exc).__name__,
            },
        )
        raise HTTPException(
            status_code=503, detail="Content source processing unavailable"
        ) from None


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
    """Refuse registry rebuilds that may change plugin runtime eligibility."""
    _audit_plugin_mutation(
        request=request,
        user=current_user,
        action="refresh_plugin_registry",
        outcome="attempt",
    )
    _audit_plugin_mutation(
        request=request,
        user=current_user,
        action="refresh_plugin_registry",
        outcome="rejected",
    )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "Plugin registry refresh requires governed lifecycle admission: "
            "the legacy reload action may enable or retire plugins without "
            "an action-bound approval."
        ),
    )


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
    """Reject legacy unapproved lifecycle calls without touching the kernel.

    The trusted PluginService.execute_approved_lifecycle entrypoint requires
    a fresh authenticated session and a database-backed action/revision-bound
    human approval. This historical route has neither, so the admin role by
    itself must not be promoted into execution authority.
    """
    action = "enable_plugin" if enabled else "disable_plugin"
    _audit_plugin_mutation(
        request=request,
        user=user,
        action=action,
        outcome="attempt",
        plugin_name=plugin_name,
    )
    _audit_plugin_mutation(
        request=request,
        user=user,
        action=action,
        outcome="rejected",
        plugin_name=plugin_name,
    )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "Plugin lifecycle approval required: this legacy action cannot "
            "execute without a fresh, actor-bound, revision-verified human approval."
        ),
    )

def _plugin_lifecycle_error(exc: Exception) -> HTTPException:
    """Return a safe denial or uncertain result without revealing SQL secrets."""
    if isinstance(exc, ApprovalNotFoundError):
        return HTTPException(status_code=404, detail="Lifecycle approval not found")
    if isinstance(exc, (ApprovalStateError, PluginLifecycleRevisionConflict,
                        PluginLifecycleApprovalRejected)):
        return HTTPException(
            status_code=409,
            detail="Lifecycle approval or global revision is no longer executable",
        )
    if isinstance(exc, (ApprovalScopeError, PermissionError)):
        return HTTPException(
            status_code=403,
            detail="Lifecycle approval is not authorized for this actor and session",
        )
    if isinstance(exc, (ValueError, TypeError)):
        return HTTPException(status_code=422, detail="Invalid plugin lifecycle request")
    # An error after the irreversible kernel step is uncertain, not success,
    # and must not trigger a browser retry without a durable receipt check.
    return HTTPException(
        status_code=503,
        detail="Plugin lifecycle outcome is unverified; inspect the durable receipt",
    )


@router.post("/{plugin_name}/lifecycle/{action}/approval")
async def request_plugin_lifecycle_approval(
    plugin_name: str,
    action: Literal["enable", "disable"],
    request: Request,
    context: ChatExecutionContext = Depends(get_plugin_lifecycle_context),
    plugin_service: PluginService = Depends(get_plugin_service),
):
    """Ask for consent using only the freshly validated bearer session."""
    principal = context.require_authenticated_user()
    _audit_plugin_mutation(
        request=request,
        user=principal,
        action="plugin_lifecycle_" + action + "_approval",
        outcome="attempt",
        plugin_name=plugin_name,
    )
    try:
        pending = await plugin_service.prepare_lifecycle_approval(
            context=context,
            plugin_id=plugin_name,
            action=action,
        )
        if pending.get("status") != "pending" or pending.get("execution_performed") is not False:
            raise RuntimeError("Lifecycle consent did not return a pending receipt")
    except Exception as exc:
        _audit_plugin_mutation(
            request=request,
            user=principal,
            action="plugin_lifecycle_" + action + "_approval",
            outcome="rejected",
            plugin_name=plugin_name,
        )
        logger.warning(
            "plugin.lifecycle.preapproval_unavailable",
            extra={"correlation_id": context.correlation_id,
                   "error_type": type(exc).__name__},
        )
        raise _plugin_lifecycle_error(exc) from exc
    _audit_plugin_mutation(
        request=request,
        user=principal,
        action="plugin_lifecycle_" + action + "_approval",
        outcome="pending",
        plugin_name=plugin_name,
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=jsonable_encoder(pending),
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/{plugin_name}/lifecycle/{action}/execute")
async def execute_plugin_lifecycle_approval(
    plugin_name: str,
    action: Literal["enable", "disable"],
    payload: LifecycleApprovalExecutionRequest,
    request: Request,
    context: ChatExecutionContext = Depends(get_plugin_lifecycle_context),
    plugin_service: PluginService = Depends(get_plugin_service),
):
    """Resume a human-approved action; no scope or roles from the client."""
    principal = context.require_authenticated_user()
    _audit_plugin_mutation(
        request=request, user=principal,
        action="plugin_lifecycle_" + action + "_execute",
        outcome="attempt", plugin_name=plugin_name,
    )
    try:
        receipt = await plugin_service.resume_lifecycle_approval(
            context=context,
            plugin_id=plugin_name,
            action=action,
            approval_id=str(payload.approval_id),
        )
        if receipt.get("status") != "verified_committed":
            raise RuntimeError("Lifecycle execution did not commit a verified receipt")
    except Exception as exc:
        _audit_plugin_mutation(
            request=request, user=principal,
            action="plugin_lifecycle_" + action + "_execute",
            outcome="unverified", plugin_name=plugin_name,
        )
        logger.warning(
            "plugin.lifecycle.execute_unverified",
            extra={"correlation_id": context.correlation_id,
                   "error_type": type(exc).__name__},
        )
        raise _plugin_lifecycle_error(exc) from exc
    _audit_plugin_mutation(
        request=request, user=principal,
        action="plugin_lifecycle_" + action + "_execute",
        outcome="verified_committed", plugin_name=plugin_name,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=jsonable_encoder(receipt),
        headers={"Cache-Control": "private, no-store"},
    )


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
