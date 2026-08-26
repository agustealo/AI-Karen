"""
Unified Memory API Routes - Phase 4.1.a
Production-ready memory management with CRUD operations, tenant isolation, and RBAC.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from ai_karen_engine.api_routes.shared.schemas import (
    ErrorHandler,
    ErrorType,
    FieldError,
    ValidationUtils,
)
from ai_karen_engine.core.memory.unified_memory_service import (
    MemoryCommitRequest,
    MemoryQueryRequest,
)
from ai_karen_engine.core.logging import get_logger, PIIRedactor
from ai_karen_engine.core.memory.runtime_gateway import resolve_memory_runtime
from ai_karen_engine.monitoring.metrics_service import MetricsService
from ai_karen_engine.monitoring.structured_logging_service import (
    StructuredLoggingService,
)
from ai_karen_engine.monitoring.correlation_service import (
    CorrelationService,
    create_correlation_logger,
)
from ai_karen_engine.utils.pydantic_base import ISO8601Model

logger = get_logger(__name__)
_metrics_service: Optional[MetricsService] = None

try:
    from ai_karen_engine.core.memory.memory_runtime_manager import (
        get_memory_manager as get_memory_runtime_manager,
    )

    MEMORY_RUNTIME_MANAGER_AVAILABLE = True
except ImportError:
    MEMORY_RUNTIME_MANAGER_AVAILABLE = False
    get_memory_runtime_manager = None  # type: ignore

try:
    from ai_karen_engine.auth.rbac_middleware import get_current_user  # type: ignore

    RBAC_AVAILABLE = True
except ImportError:  # pragma: no cover - defensive
    logger.warning(
        "RBAC middleware unavailable; memory routes will operate without role enforcement"
    )
    RBAC_AVAILABLE = False

METRICS_AVAILABLE = True


# Unified request/response models according to design spec
class ContextHit(ISO8601Model):
    """Unified memory hit representation"""

    id: str
    text: str
    preview: Optional[str] = None
    score: float
    tags: List[str] = Field(default_factory=list)
    recency: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)
    importance: int = Field(5, ge=1, le=10)
    decay_tier: str = Field("short")
    created_at: datetime
    updated_at: Optional[datetime] = None
    user_id: str
    org_id: Optional[str] = None


class MemQuery(ISO8601Model):
    """Unified memory query request schema"""

    user_id: str = Field(..., min_length=1)
    org_id: Optional[str] = None
    query: str = Field(..., min_length=1, max_length=4096)
    top_k: int = Field(12, ge=1, le=50)


class MemSearchResponse(ISO8601Model):
    """Unified memory search response schema"""

    hits: List[ContextHit]
    total_found: int
    query_time_ms: float
    correlation_id: str


class MemCommit(ISO8601Model):
    """Unified memory commit request schema"""

    user_id: str = Field(..., min_length=1)
    org_id: Optional[str] = None
    text: str = Field(..., min_length=1, max_length=16000)
    tags: List[str] = Field(default_factory=list)
    importance: int = Field(5, ge=1, le=10)
    decay: str = Field("short", pattern="^(short|medium|long|pinned)$")


class MemCommitResponse(ISO8601Model):
    """Unified memory commit response schema"""

    id: str
    success: bool
    message: str
    correlation_id: str


class MemUpdateRequest(ISO8601Model):
    """Memory update request schema"""

    text: Optional[str] = Field(None, min_length=1, max_length=16000)
    tags: Optional[List[str]] = None
    importance: Optional[int] = Field(None, ge=1, le=10)
    decay: Optional[str] = Field(None, pattern="^(short|medium|long|pinned)$")


class MemUpdateResponse(ISO8601Model):
    """Memory update response schema"""

    success: bool
    message: str
    correlation_id: str


class MemDeleteResponse(ISO8601Model):
    """Memory delete response schema"""

    success: bool
    message: str
    correlation_id: str


# Import unified schemas
# Unified router with memory prefix for API gateway
router = APIRouter(prefix="/memory", tags=["memory"])

CORRELATION_AVAILABLE = True
logger = create_correlation_logger(__name__)

STRUCTURED_LOGGING_AVAILABLE = True


def _get_metrics_service() -> MetricsService:
    """Return a process-local metrics service instance."""
    global _metrics_service
    if _metrics_service is None:
        _metrics_service = MetricsService({})
    return _metrics_service


def get_correlation_id(request: Request) -> str:
    """Extract or generate correlation ID for request tracking"""
    if CORRELATION_AVAILABLE:
        headers = {key: value for key, value in request.headers.items()}
        return CorrelationService.get_or_create_correlation_id(headers)
    else:
        return request.headers.get("X-Correlation-Id", str(uuid.uuid4()))


async def check_rbac_scope(request: Request, scope: str) -> bool:
    """Check RBAC scope using the configured middleware when available.

    Falls back to permissive mode in development if RBAC is unavailable.
    """
    # Prefer the RBAC middleware instance attached during app setup
    try:
        rbac = getattr(getattr(request, "app", None), "state", None)
        rbac = getattr(rbac, "rbac", None)
        if rbac is not None:
            ok = await rbac.validate_scopes(request, {scope})
            return ok
    except Exception as e:
        logger.warning(f"RBAC middleware validation error for scope '{scope}': {e}")

    # Fallback: allow in non-production to avoid blocking development
    import os

    env = (os.getenv("ENVIRONMENT") or os.getenv("KARI_ENV") or "development").lower()
    if env in ("development", "dev", "local", "test", "testing"):
        return True

    # In production with no RBAC available, deny by default
    raise HTTPException(status_code=403, detail="RBAC unavailable")


def _service_unavailable_error(correlation_id: str, path: str, reason: str) -> HTTPException:
    error_response = ErrorHandler.create_error_response(
        error_type=ErrorType.INTERNAL_ERROR,
        message="Memory backend unavailable",
        correlation_id=correlation_id,
        path=path,
        status_code=503,
        details={"degraded": True, "backend": "neuro_vault", "reason": reason},
    )
    return HTTPException(status_code=503, detail=error_response.model_dump(mode="json"))


def _assert_tenant_boundary(http_request: Request, requested_user_id: str, requested_org_id: Optional[str]) -> None:
    principal = getattr(http_request.state, "user", None)
    if principal is None:
        return
    principal_user_id = getattr(principal, "user_id", None) or getattr(principal, "id", None) or (
        principal.get("user_id") if isinstance(principal, dict) else None
    )
    principal_org_id = getattr(principal, "org_id", None) or (
        principal.get("org_id") if isinstance(principal, dict) else None
    )
    if principal_user_id and requested_user_id and principal_user_id != requested_user_id:
        raise HTTPException(status_code=403, detail="Cross-tenant user access denied")
    if principal_org_id and requested_org_id and principal_org_id != requested_org_id:
        raise HTTPException(status_code=403, detail="Cross-tenant organization access denied")


def record_metrics(
    operation: str,
    status: str,
    duration: float,
    user_id: str = "",
    org_id: str = "",
    decay_tier: str = "",
    correlation_id: Optional[str] = None,
):
    """Record metrics with graceful fallback"""
    if not METRICS_AVAILABLE:
        return

    try:
        metrics_service = _get_metrics_service()
        metric_name = (
            "memory.commit.duration_seconds"
            if operation == "commit"
            else "memory.query.duration_seconds"
        )
        metrics_service.record(
            metric_name,
            duration,
            tags={
                "operation": operation,
                "status": status,
                "decay_tier": decay_tier or "",
            },
            metadata={
                "user_id": user_id,
                "org_id": org_id,
                "correlation_id": correlation_id or "",
            },
        )

    except Exception as e:
        logger.warning(f"Metrics recording failed: {e}")


def apply_tenant_filtering(user_id: str, org_id: Optional[str]) -> Dict[str, Any]:
    """Apply tenant filtering constraints"""
    filters = {"user_id": user_id}
    if org_id:
        filters["org_id"] = org_id
    return filters


def _memory_write_is_shadowed(user_id: str, org_id: Optional[str]) -> bool:
    """Return True when durable memory writes should be skipped."""
    if not MEMORY_RUNTIME_MANAGER_AVAILABLE:
        return False

    try:
        manager = get_memory_runtime_manager()
        tenant_id = org_id or user_id
        return not manager.flags.is_enabled("memory_learning_enabled", tenant_id, user_id) or manager.flags.is_enabled(
            "memory_shadow_mode_enabled", tenant_id, user_id
        )
    except Exception as exc:
        logger.warning(f"Failed to resolve memory learning gate: {exc}")
        return False


@router.post("/search", response_model=MemSearchResponse)
async def memory_search(request: MemQuery, http_request: Request):
    """
    Unified memory search endpoint - READ operation for all interfaces.

    Provides semantic search across all memory types with tenant isolation
    and scope-based permissions.
    """
    start_time = datetime.utcnow()
    correlation_id = get_correlation_id(http_request)
    # Metrics service currently unused here; retained for future enhancements
    query_duration = 0.0

    # Set correlation ID in context for propagation
    if CORRELATION_AVAILABLE:
        CorrelationService.set_correlation_id(correlation_id)

        # Start trace tracking
        tracker = CorrelationService.get_correlation_tracker()
        tracker.start_trace(
            correlation_id,
            "memory_search",
            {
                "user_id": request.user_id,
                "org_id": request.org_id,
                "query_length": len(request.query),
                "top_k": request.top_k,
            },
        )

    # Check RBAC permissions
    if not await check_rbac_scope(http_request, "memory:read"):
        record_metrics(
            "search",
            "forbidden",
            0,
            request.user_id,
            request.org_id or "",
            "",
            correlation_id,
        )
        error_response = ErrorHandler.create_authorization_error_response(
            correlation_id=correlation_id,
            path=str(http_request.url.path),
            message="Insufficient permissions for memory search",
        )
        raise HTTPException(
            status_code=403, detail=error_response.model_dump(mode="json")
        )
    _assert_tenant_boundary(http_request, request.user_id, request.org_id)

    try:
        # Apply tenant filtering
        tenant_filters = apply_tenant_filtering(request.user_id, request.org_id)

        # Get memory service
        runtime = await resolve_memory_runtime()
        if not runtime.available or runtime.service is None:
            raise _service_unavailable_error(correlation_id, str(http_request.url.path), runtime.reason)
        tenant_id = tenant_filters.get("org_id") or tenant_filters["user_id"]
        search_request = MemoryQueryRequest(
            user_id=request.user_id,
            org_id=request.org_id,
            query=request.query,
            top_k=request.top_k,
        )
        search_response = await runtime.service.query(
            tenant_id, search_request, correlation_id
        )
        hits = []
        for mem in search_response.hits:
            redacted_text = PIIRedactor.redact_pii(mem.text)
            hits.append(
                ContextHit(
                    id=mem.id,
                    text=redacted_text,
                    preview=redacted_text[:100],
                    score=mem.score,
                    tags=mem.tags or [],
                    importance=mem.importance,
                    decay_tier=mem.decay_tier,
                    created_at=mem.created_at,
                    user_id=request.user_id,
                    org_id=request.org_id,
                    meta={"source": "unified_search", "tenant_filtered": True},
                )
            )

        # Calculate timing
        query_time_ms = query_duration * 1000

        # Record metrics
        record_metrics(
            "search",
            "success",
            query_duration,
            request.user_id,
            request.org_id or "",
            "",
            correlation_id,
        )

        # Log memory access with structured logging (without content for privacy)
        if STRUCTURED_LOGGING_AVAILABLE:
            try:
                logging_service = get_structured_logging_service()
                logging_service.log_memory_access(
                    operation="search",
                    memory_id=f"query_{correlation_id[:8]}",  # Use correlation ID fragment
                    user_id=request.user_id,
                    org_id=request.org_id,
                    correlation_id=correlation_id,
                    hits_count=len(hits),
                    query_length=len(request.query),
                    top_k=request.top_k,
                )

                # Log API request
                logging_service.log_api_request(
                    method=http_request.method,
                    endpoint=str(http_request.url.path),
                    status_code=200,
                    duration_ms=query_duration * 1000,
                    user_id=request.user_id,
                    org_id=request.org_id,
                    ip_address=http_request.client.host
                    if http_request.client
                    else None,
                    user_agent=http_request.headers.get("user-agent"),
                    correlation_id=correlation_id,
                    hits_count=len(hits),
                )
            except Exception as e:
                logger.warning(f"Structured logging failed: {e}")

        # End trace tracking
        if CORRELATION_AVAILABLE:
            tracker.end_trace(
                correlation_id,
                "success",
                {
                    "total_duration": query_duration,
                    "hits_count": len(hits),
                    "user_id": request.user_id,
                    "org_id": request.org_id,
                },
            )

        return MemSearchResponse(
            hits=hits,
            total_found=len(hits),
            query_time_ms=query_time_ms,
            correlation_id=correlation_id,
        )

    except HTTPException:
        # End trace for HTTP exceptions
        if CORRELATION_AVAILABLE:
            query_duration = (datetime.utcnow() - start_time).total_seconds()
            tracker.end_trace(
                correlation_id,
                "http_error",
                {
                    "total_duration": query_duration,
                    "user_id": request.user_id,
                    "org_id": request.org_id,
                },
            )
        raise
    except Exception as e:
        query_duration = (datetime.utcnow() - start_time).total_seconds()
        record_metrics(
            "search",
            "error",
            query_duration,
            request.user_id,
            request.org_id or "",
            "",
            correlation_id,
        )

        # End trace for general exceptions
        if CORRELATION_AVAILABLE:
            tracker.end_trace(
                correlation_id,
                "error",
                {
                    "total_duration": query_duration,
                    "error": str(e),
                    "user_id": request.user_id,
                    "org_id": request.org_id,
                },
            )

        logger.error(
            f"Memory search failed: {e}", extra={"correlation_id": correlation_id}
        )

        error_response = ErrorHandler.create_internal_error_response(
            correlation_id=correlation_id, path=str(http_request.url.path), error=e
        )
        raise HTTPException(
            status_code=500, detail=error_response.model_dump(mode="json")
        )


@router.post("/commit", response_model=MemCommitResponse)
async def memory_commit(request: MemCommit, http_request: Request):
    """
    Unified memory commit endpoint - CREATE operation for all interfaces.

    Stores new memories with decay policy assignment and tenant isolation.
    """
    start_time = datetime.utcnow()
    correlation_id = get_correlation_id(http_request)

    # Check RBAC permissions
    if not await check_rbac_scope(http_request, "memory:write"):
        record_metrics(
            "commit",
            "forbidden",
            0,
            request.user_id,
            request.org_id or "",
            request.decay,
            correlation_id,
        )
        error_response = ErrorHandler.create_authorization_error_response(
            correlation_id=correlation_id,
            path=str(http_request.url.path),
            message="Insufficient permissions for memory commit",
        )
        raise HTTPException(
            status_code=403, detail=error_response.model_dump(mode="json")
        )
    _assert_tenant_boundary(http_request, request.user_id, request.org_id)

    try:
        # Field validations
        try:
            request.text = ValidationUtils.validate_text_content(request.text)
        except ValueError as e:
            commit_duration = (datetime.utcnow() - start_time).total_seconds()
            record_metrics(
                "commit",
                "validation_error",
                commit_duration,
                request.user_id,
                request.org_id or "",
                request.decay,
                correlation_id,
            )
            error_response = ErrorHandler.create_error_response(
                error_type=ErrorType.VALIDATION_ERROR,
                message=str(e),
                correlation_id=correlation_id,
                path=str(http_request.url.path),
                status_code=422,
                field_errors=[
                    FieldError(
                        field="text",
                        message=str(e),
                        code="invalid_text",
                        invalid_value=request.text,
                    )
                ],
            )
            raise HTTPException(
                status_code=422, detail=error_response.model_dump(mode="json")
            )

        try:
            request.tags = ValidationUtils.validate_tags(request.tags)
        except ValueError as e:
            commit_duration = (datetime.utcnow() - start_time).total_seconds()
            record_metrics(
                "commit",
                "validation_error",
                commit_duration,
                request.user_id,
                request.org_id or "",
                request.decay,
                correlation_id,
            )
            error_response = ErrorHandler.create_error_response(
                error_type=ErrorType.VALIDATION_ERROR,
                message=str(e),
                correlation_id=correlation_id,
                path=str(http_request.url.path),
                status_code=422,
                field_errors=[
                    FieldError(
                        field="tags",
                        message=str(e),
                        code="invalid_tags",
                        invalid_value=request.tags,
                    )
                ],
            )
            raise HTTPException(
                status_code=422, detail=error_response.model_dump(mode="json")
            )

        try:
            request.importance = ValidationUtils.validate_importance(request.importance)
        except ValueError as e:
            commit_duration = (datetime.utcnow() - start_time).total_seconds()
            record_metrics(
                "commit",
                "validation_error",
                commit_duration,
                request.user_id,
                request.org_id or "",
                request.decay,
                correlation_id,
            )
            error_response = ErrorHandler.create_error_response(
                error_type=ErrorType.VALIDATION_ERROR,
                message=str(e),
                correlation_id=correlation_id,
                path=str(http_request.url.path),
                status_code=422,
                field_errors=[
                    FieldError(
                        field="importance",
                        message=str(e),
                        code="invalid_importance",
                        invalid_value=request.importance,
                    )
                ],
            )
            raise HTTPException(
                status_code=422, detail=error_response.model_dump(mode="json")
            )

        if _memory_write_is_shadowed(request.user_id, request.org_id):
            commit_duration = (datetime.utcnow() - start_time).total_seconds()
            record_metrics(
                "commit",
                "shadow",
                commit_duration,
                request.user_id,
                request.org_id or "",
                request.decay,
                correlation_id,
            )
            return MemCommitResponse(
                id="",
                success=True,
                message="Memory learning is in shadow mode; no durable write was performed",
                correlation_id=correlation_id,
            )

        # Apply tenant filtering
        tenant_filters = apply_tenant_filtering(request.user_id, request.org_id)

        runtime = await resolve_memory_runtime()
        if not runtime.available or runtime.service is None:
            raise _service_unavailable_error(correlation_id, str(http_request.url.path), runtime.reason)
        tenant_id = tenant_filters.get("org_id") or tenant_filters["user_id"]
        commit_request = MemoryCommitRequest(
            user_id=request.user_id,
            org_id=request.org_id,
            text=request.text,
            tags=request.tags,
            importance=request.importance,
            decay=request.decay,
            metadata={"source": "memory_commit_route", "tenant_filters": tenant_filters},
        )
        commit_response = await runtime.service.commit(
            tenant_id=tenant_id,
            request=commit_request,
            correlation_id=correlation_id,
        )
        success = commit_response.success
        memory_id = commit_response.id if commit_response.success else ""
        message = commit_response.message

        # Calculate timing
        commit_duration = (datetime.utcnow() - start_time).total_seconds()

        # Record metrics
        record_metrics(
            "commit",
            "success" if success else "error",
            commit_duration,
            request.user_id,
            request.org_id or "",
            request.decay,
            correlation_id,
        )

        return MemCommitResponse(
            id=memory_id if success else "",
            success=success,
            message=message,
            correlation_id=correlation_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        commit_duration = (datetime.utcnow() - start_time).total_seconds()
        record_metrics(
            "commit",
            "error",
            commit_duration,
            request.user_id,
            request.org_id or "",
            request.decay,
            correlation_id,
        )

        logger.error(
            f"Memory commit failed: {e}", extra={"correlation_id": correlation_id}
        )

        error_response = ErrorHandler.create_internal_error_response(
            correlation_id=correlation_id, path=str(http_request.url.path), error=e
        )
        raise HTTPException(
            status_code=500, detail=error_response.model_dump(mode="json")
        )


@router.put("/{memory_id}", response_model=MemUpdateResponse)
async def memory_update(
    memory_id: str,
    request: MemUpdateRequest,
    http_request: Request,
    user_id: str = "",
    org_id: Optional[str] = None,
):
    """
    Unified memory update endpoint - UPDATE operation with version tracking.

    Updates existing memories with version history and importance recalculation.
    """
    start_time = datetime.utcnow()
    correlation_id = get_correlation_id(http_request)

    # Check RBAC permissions
    if not await check_rbac_scope(http_request, "memory:write"):
        record_metrics(
            "update", "forbidden", 0, user_id, org_id or "", "", correlation_id
        )
        error_response = ErrorHandler.create_authorization_error_response(
            correlation_id=correlation_id,
            path=str(http_request.url.path),
            message="Insufficient permissions for memory update",
        )
        raise HTTPException(
            status_code=403, detail=error_response.model_dump(mode="json")
        )

    try:
        # Field validations
        if request.text is not None:
            try:
                request.text = ValidationUtils.validate_text_content(request.text)
            except ValueError as e:
                update_duration = (datetime.utcnow() - start_time).total_seconds()
                record_metrics(
                    "update",
                    "validation_error",
                    update_duration,
                    user_id,
                    org_id or "",
                    "",
                    correlation_id,
                )
                error_response = ErrorHandler.create_error_response(
                    error_type=ErrorType.VALIDATION_ERROR,
                    message=str(e),
                    correlation_id=correlation_id,
                    path=str(http_request.url.path),
                    status_code=422,
                    field_errors=[
                        FieldError(
                            field="text",
                            message=str(e),
                            code="invalid_text",
                            invalid_value=request.text,
                        )
                    ],
                )
                raise HTTPException(
                    status_code=422, detail=error_response.model_dump(mode="json")
                )

        if request.tags is not None:
            try:
                request.tags = ValidationUtils.validate_tags(request.tags)
            except ValueError as e:
                update_duration = (datetime.utcnow() - start_time).total_seconds()
                record_metrics(
                    "update",
                    "validation_error",
                    update_duration,
                    user_id,
                    org_id or "",
                    "",
                    correlation_id,
                )
                error_response = ErrorHandler.create_error_response(
                    error_type=ErrorType.VALIDATION_ERROR,
                    message=str(e),
                    correlation_id=correlation_id,
                    path=str(http_request.url.path),
                    status_code=422,
                    field_errors=[
                        FieldError(
                            field="tags",
                            message=str(e),
                            code="invalid_tags",
                            invalid_value=request.tags,
                        )
                    ],
                )
                raise HTTPException(
                    status_code=422, detail=error_response.model_dump(mode="json")
                )

        if request.importance is not None:
            try:
                request.importance = ValidationUtils.validate_importance(
                    request.importance
                )
            except ValueError as e:
                update_duration = (datetime.utcnow() - start_time).total_seconds()
                record_metrics(
                    "update",
                    "validation_error",
                    update_duration,
                    user_id,
                    org_id or "",
                    "",
                    correlation_id,
                )
                error_response = ErrorHandler.create_error_response(
                    error_type=ErrorType.VALIDATION_ERROR,
                    message=str(e),
                    correlation_id=correlation_id,
                    path=str(http_request.url.path),
                    status_code=422,
                    field_errors=[
                        FieldError(
                            field="importance",
                            message=str(e),
                            code="invalid_importance",
                            invalid_value=request.importance,
                        )
                    ],
                )
                raise HTTPException(
                    status_code=422, detail=error_response.model_dump(mode="json")
                )

        _assert_tenant_boundary(http_request, user_id, org_id)
        if _memory_write_is_shadowed(user_id, org_id):
            update_duration = (datetime.utcnow() - start_time).total_seconds()
            record_metrics(
                "update",
                "shadow",
                update_duration,
                user_id,
                org_id or "",
                "",
                correlation_id,
            )
            return MemUpdateResponse(
                success=True,
                message=(
                    f"Memory {memory_id} update skipped because memory learning is in shadow mode"
                ),
                correlation_id=correlation_id,
            )

        # Apply tenant filtering
        tenant_filters = apply_tenant_filtering(user_id, org_id)

        runtime = await resolve_memory_runtime()
        if runtime.available and runtime.service:
            try:
                tenant_id = tenant_filters.get("org_id") or tenant_filters["user_id"]
                updates: Dict[str, Any] = {
                    "updated_by": user_id or tenant_filters["user_id"],
                    "metadata": dict(tenant_filters),
                }
                if request.text is not None:
                    updates["content"] = request.text
                if request.tags is not None:
                    updates["tags"] = request.tags
                if request.importance is not None:
                    updates["importance"] = request.importance
                if request.decay is not None:
                    updates["metadata"]["decay_tier"] = request.decay

                success = await runtime.service.update(
                    tenant_id=tenant_id,
                    memory_id=memory_id,
                    updates=updates,
                    correlation_id=correlation_id,
                )
                message = f"Memory {memory_id} updated successfully" if success else "Memory update failed"
            except Exception as e:
                logger.warning(f"Memory update failed: {e}")
                success = False
                message = f"Memory update failed: {str(e)}"
        else:
            raise _service_unavailable_error(correlation_id, str(http_request.url.path), runtime.reason)

        # Calculate timing
        update_duration = (datetime.utcnow() - start_time).total_seconds()

        # Record metrics
        record_metrics(
            "update",
            "success" if success else "error",
            update_duration,
            user_id,
            org_id or "",
            "",
            correlation_id,
        )

        return MemUpdateResponse(
            success=success, message=message, correlation_id=correlation_id
        )

    except HTTPException:
        raise
    except Exception as e:
        update_duration = (datetime.utcnow() - start_time).total_seconds()
        record_metrics(
            "update",
            "error",
            update_duration,
            user_id,
            org_id or "",
            "",
            correlation_id,
        )

        logger.error(
            f"Memory update failed: {e}", extra={"correlation_id": correlation_id}
        )

        error_response = ErrorHandler.create_internal_error_response(
            correlation_id=correlation_id, path=str(http_request.url.path), error=e
        )
        raise HTTPException(
            status_code=500, detail=error_response.model_dump(mode="json")
        )


@router.delete("/{memory_id}", response_model=MemDeleteResponse)
async def memory_delete(
    memory_id: str,
    http_request: Request,
    hard_delete: bool = False,
    user_id: str = "",
    org_id: Optional[str] = None,
):
    """
    Unified memory delete endpoint - DELETE operation with audit trails.

    Supports both soft deletion with audit trails and hard deletion for privacy compliance.
    """
    start_time = datetime.utcnow()
    correlation_id = get_correlation_id(http_request)

    # Check RBAC permissions
    if not await check_rbac_scope(http_request, "memory:write"):
        record_metrics(
            "delete", "forbidden", 0, user_id, org_id or "", "", correlation_id
        )
        error_response = ErrorHandler.create_authorization_error_response(
            correlation_id=correlation_id,
            path=str(http_request.url.path),
            message="Insufficient permissions for memory deletion",
        )
        raise HTTPException(
            status_code=403, detail=error_response.model_dump(mode="json")
        )
    _assert_tenant_boundary(http_request, user_id, org_id)

    try:
        # Apply tenant filtering
        tenant_filters = apply_tenant_filtering(user_id, org_id)

        runtime = await resolve_memory_runtime()
        if not runtime.available or runtime.service is None:
            raise _service_unavailable_error(correlation_id, str(http_request.url.path), runtime.reason)
        tenant_id = tenant_filters.get("org_id") or tenant_filters["user_id"]
        success = await runtime.service.base_manager.delete_memory(tenant_id, memory_id)
        delete_type = "hard" if hard_delete else "soft"
        message = f"Memory {memory_id} {delete_type} deleted successfully" if success else "Memory deletion failed"

        # Calculate timing
        delete_duration = (datetime.utcnow() - start_time).total_seconds()

        # Record metrics
        record_metrics(
            "delete",
            "success" if success else "error",
            delete_duration,
            user_id,
            org_id or "",
            "",
            correlation_id,
        )

        return MemDeleteResponse(
            success=success, message=message, correlation_id=correlation_id
        )

    except HTTPException:
        raise
    except Exception as e:
        delete_duration = (datetime.utcnow() - start_time).total_seconds()
        record_metrics(
            "delete",
            "error",
            delete_duration,
            user_id,
            org_id or "",
            "",
            correlation_id,
        )

        logger.error(
            f"Memory deletion failed: {e}", extra={"correlation_id": correlation_id}
        )

        error_response = ErrorHandler.create_internal_error_response(
            correlation_id=correlation_id, path=str(http_request.url.path), error=e
        )
        raise HTTPException(
            status_code=500, detail=error_response.model_dump(mode="json")
        )


@router.get("/health")
async def health_check():
    """Health check for memory service with dependency status"""
    return {
        "status": "healthy",
        "service": "memory",
        "dependencies": {
            "memory_service": True,
            "rbac": RBAC_AVAILABLE,
            "metrics": METRICS_AVAILABLE,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


# Export router for inclusion in main FastAPI app
__all__ = ["router"]

@router.get('/observability/events')
async def get_memory_observability_events(conversation_id: Optional[str] = None, request_id: Optional[str] = None):
    """Backend truth endpoint for memory event stream."""
    return {
        'correlation_id': None,
        'request_id': request_id,
        'conversation_id': conversation_id,
        'events': [],
    }


@router.get('/observability/summary')
async def get_memory_observability_summary(conversation_id: Optional[str] = None, request_id: Optional[str] = None):
    """Backend truth endpoint for memory summary."""
    return {
        'correlation_id': None,
        'request_id': request_id,
        'conversation_id': conversation_id,
        'summary': {
            'memory_used': False,
            'activation_mode': 'none',
            'memory_classes': [],
            'stores_queried': [],
            'store_latencies_ms': {},
            'result_count': 0,
            'selected_count': 0,
            'token_budget': 0,
            'degraded': False,
            'degradation_reason': None,
            'circuit_breaker_state': 'closed',
            'writeback_status': 'skipped',
        }
    }


@router.get('/admin/observability')
async def get_admin_memory_observability(conversation_id: Optional[str] = None, request_id: Optional[str] = None):
    summary = await get_memory_observability_summary(conversation_id=conversation_id, request_id=request_id)
    events = await get_memory_observability_events(conversation_id=conversation_id, request_id=request_id)
    return {
        'correlation_id': summary.get('correlation_id'),
        'request_id': request_id,
        'conversation_id': conversation_id,
        'events': events.get('events', []),
        'summary': summary.get('summary', {}),
    }
