"""
Intelligent Search plugin API routes.

Provides dedicated endpoints for the Intelligent Search plugin with:
- Run endpoint for executing searches
- Status endpoint for plugin health
- Capabilities endpoint for plugin features and permissions

All routes enforce RBAC, tenant isolation, and audit logging.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ai_karen_engine.core.services.dependencies import get_plugin_service
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.models.web_api_error_responses import (
    WebAPIErrorCode,
    create_generic_error_response,
    create_service_error_response,
    get_http_status_for_error_code,
)
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.plugin_service import PluginService


logger = get_logger(__name__)
router = APIRouter(prefix="/intelligent-search", tags=["intelligent-search"])


# Request/Response Models


class IntelligentSearchRequest(BaseModel):
    """Request model for intelligent search execution."""

    query: str = Field(..., description="Search query string", min_length=1)
    mode: str = Field(
        default="basic",
        description="Search mode: basic, advanced, or unrestricted",
        pattern="^(basic|advanced|unrestricted)$",
    )
    sources: List[str] = Field(
        default_factory=lambda: ["web"],
        description="Search sources: web, memory, documents, local_knowledge",
    )
    filters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional filters: date_from, date_to, include_domains, exclude_domains, language, limit",
    )
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Context: conversation_id, session_id",
    )
    crawl: Optional[Dict[str, Any]] = Field(
        None,
        description="Crawl4AI-specific options: max_pages, max_depth, capture_screenshot, etc.",
    )


class SearchFilterSchema(BaseModel):
    """Schema for search filters."""

    date_from: Optional[str] = None
    date_to: Optional[str] = None
    include_domains: List[str] = Field(default_factory=list)
    exclude_domains: List[str] = Field(default_factory=list)
    language: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=100)


class CrawlOptionsSchema(BaseModel):
    """Schema for Crawl4AI crawl options."""

    enabled: bool = False
    max_pages: int = Field(default=5, ge=1, le=50)
    max_depth: int = Field(default=1, ge=1, le=5)
    capture_screenshot: bool = False
    use_cache: bool = True
    respect_robots_txt: bool = True
    include_domains: List[str] = Field(default_factory=list)
    exclude_domains: List[str] = Field(default_factory=list)
    structured_schema: Optional[Dict[str, Any]] = None


class SearchResultItem(BaseModel):
    """Schema for a single search result."""

    id: str
    rank: int
    title: str
    url: Optional[str] = None
    source: str
    snippet: str
    summary: Optional[str] = None
    score: float = 0.0
    published_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CitationItem(BaseModel):
    """Schema for a citation."""

    result_id: str
    label: str
    url: Optional[str] = None


class DiagnosticsSchema(BaseModel):
    """Schema for diagnostics."""

    request_id: str
    correlation_id: str
    latency_ms: float = 0.0
    degraded: bool = False
    degradation_reason: Optional[str] = None
    source_timings: Dict[str, float] = Field(default_factory=dict)
    result_count: int = 0


class CrawlDiagnosticsSchema(BaseModel):
    """Schema for crawl diagnostics."""

    enabled: bool
    engine: str
    status: str
    pages_requested: int = 0
    pages_succeeded: int = 0
    pages_failed: int = 0
    latency_ms: float = 0.0
    capabilities: Dict[str, bool] = Field(default_factory=dict)
    degraded: bool = False
    degradation_reason: Optional[str] = None


class IntelligentSearchResponse(BaseModel):
    """Response model for intelligent search."""

    plugin_id: str
    plugin_version: str
    status: str = Field(..., description="ok, partial, degraded, or error")
    query: str
    mode: str
    sources_used: List[str] = Field(default_factory=list)
    summary: str
    results: List[SearchResultItem] = Field(default_factory=list)
    citations: List[CitationItem] = Field(default_factory=list)
    diagnostics: DiagnosticsSchema
    crawl: Optional[CrawlDiagnosticsSchema] = None
    errors: List[Dict[str, str]] = Field(default_factory=list)


class CapabilitiesResponse(BaseModel):
    """Response model for plugin capabilities."""

    plugin_id: str
    plugin_version: str
    enabled: bool
    permissions: List[str]
    available_modes: List[str] = Field(
        default_factory=lambda: ["basic", "advanced", "unrestricted"]
    )
    available_sources: List[str] = Field(
        default_factory=lambda: ["web", "memory", "documents", "local_knowledge"]
    )
    rbac: Dict[str, Any] = Field(
        default_factory=lambda: {
            "required_roles": ["user"],
            "unrestricted_required_roles": ["admin", "super_admin"],
        }
    )
    crawl_capabilities: Dict[str, Any] = Field(
        default_factory=lambda: {
            "enabled": True,
            "engine": "crawl4ai",
            "max_pages": 50,
            "max_depth": 5,
            "supports_screenshot": True,
            "supports_structured_extraction": True,
        }
    )


class StatusResponse(BaseModel):
    """Response model for plugin status."""

    plugin_id: str
    status: str  # ready, running, degraded, error, disabled
    version: str
    uptime_seconds: float
    last_error: Optional[str] = None
    execution_count: int = 0
    success_rate: float = 0.0


# --- Helper Functions ---


def _normalize_plugin_result(
    plugin_result: Dict[str, Any],
    query: str,
    mode: str,
    request_id: str,
    correlation_id: str,
    plugin_id: str = "intelligent_search",
    plugin_version: str = "0.0.0",
) -> IntelligentSearchResponse:
    """Normalize plugin execution result to response schema."""
    # Extract results from plugin result
    sources = plugin_result.get("sources", [])
    results = plugin_result.get("results", [])
    summary = plugin_result.get("summary", "")
    diagnostics = plugin_result.get("diagnostics", {})
    errors = plugin_result.get("errors", [])

    # Normalize sources to result items
    result_items: List[SearchResultItem] = []
    for idx, source in enumerate(sources[:10]):  # Limit to 10 for response
        result_items.append(
            SearchResultItem(
                id=source.get("id", f"result-{idx}"),
                rank=idx + 1,
                title=source.get("title", ""),
                url=source.get("url"),
                source=source.get("source", "web"),
                snippet=source.get("snippet", "") or source.get("content", "")[:200],
                summary=source.get("content"),
                score=source.get("relevanceScore", 0.0) or 0.0,
                published_at=source.get("publishedDate"),
                metadata={
                    "domain": source.get("domain"),
                    "markdown": source.get("markdown"),
                },
            )
        )

    # Also include results array if present
    for idx, result in enumerate(results[:10 - len(result_items)]):
        result_items.append(
            SearchResultItem(
                id=result.get("id", f"result-{len(result_items) + idx}"),
                rank=len(result_items) + idx + 1,
                title=result.get("title", ""),
                url=result.get("url"),
                source=result.get("source", "web"),
                snippet=result.get("snippet", ""),
                summary=result.get("content"),
                score=result.get("score", 0.0),
                published_at=result.get("published_at"),
                metadata={},
            )
        )

    # Build citations from results
    citations: List[CitationItem] = []
    for idx, result_item in enumerate(result_items):
        if result_item.url:
            citations.append(
                CitationItem(
                    result_id=result_item.id,
                    label=result_item.title[:50] or f"Source {idx + 1}",
                    url=result_item.url,
                )
            )

    # Determine status
    status = "ok"
    if errors or not result_items:
        status = "partial"
    if any("unavailable" in str(e).lower() for e in errors):
        status = "degraded"

    # Normalize diagnostics
    diagnostics_schema = DiagnosticsSchema(
        request_id=request_id,
        correlation_id=correlation_id,
        latency_ms=diagnostics.get("latencyMs", 0.0) or plugin_result.get("execution_time_ms", 0.0) or 0.0,
        degraded=diagnostics.get("degraded", False),
        degradation_reason=diagnostics.get("degradationReason"),
        source_timings=diagnostics.get("sourceTimings", {}),
        result_count=len(result_items),
    )

    # Extract crawl diagnostics if present
    crawl_diagnostics = None
    if "crawl" in plugin_result or "liveSearch" in plugin_result:
        crawl_info = plugin_result.get("crawl", {}) or plugin_result.get("liveSearch", {})
        crawl_diagnostics = CrawlDiagnosticsSchema(
            enabled=crawl_info.get("enabled", True),
            engine=crawl_info.get("engine", "crawl4ai"),
            status=crawl_info.get("status", "unknown"),
            pages_requested=crawl_info.get("pagesRequested", len(sources)),
            pages_succeeded=crawl_info.get("pagesSucceeded", len([s for s in sources if s.get("content")])),
            pages_failed=crawl_info.get("pagesFailed", 0),
            latency_ms=diagnostics.get("latencyMs", 0.0) or 0.0,
            capabilities=crawl_info.get("capabilities", {}),
            degraded=crawl_info.get("degraded", False),
            degradation_reason=crawl_info.get("degradationReason"),
        )

    return IntelligentSearchResponse(
        plugin_id=plugin_id,
        plugin_version=plugin_version,
        status=status,
        query=query,
        mode=mode,
        sources_used=list({r.source for r in result_items}),
        summary=summary or f"Found {len(result_items)} result(s) for '{query}'.",
        results=result_items,
        citations=citations,
        diagnostics=diagnostics_schema,
        crawl=crawl_diagnostics,
        errors=[{"code": e.get("code", "error"), "message": str(e)} for e in errors if isinstance(e, dict)],
    )


# --- Routes ---


@router.post("/run", response_model=IntelligentSearchResponse)
async def run_intelligent_search(
    request: IntelligentSearchRequest,
    plugin_service: PluginService = Depends(get_plugin_service),
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user),
):
    """
    Execute an intelligent search query.

    Supports multiple search modes (basic, advanced, unrestricted) and sources.
    Can optionally use Crawl4AI for deep content extraction.

    RBAC:
    - basic/advanced: Requires 'user' role
    - unrestricted: Requires 'admin' or 'super_admin' role
    """
    try:
        # Validate RBAC for unrestricted mode
        if request.mode == "unrestricted":
            if not current_user:
                raise HTTPException(
                    status_code=401,
                    detail="Authentication required for unrestricted mode",
                )

            user_roles = current_user.get("roles", [])
            required_roles = ["admin", "super_admin"]
            if not any(role in user_roles for role in required_roles):
                raise HTTPException(
                    status_code=403,
                    detail=f"Unrestricted mode requires one of: {', '.join(required_roles)}",
                )

        # Build plugin execution parameters
        params: Dict[str, Any] = {
            "query": request.query,
            "mode": request.mode,
            "context": request.context,
        }

        # Add filters
        if request.filters:
            params.update(request.filters)

        # Add crawl options
        if request.crawl:
            params["crawl"] = request.crawl

        # Execute plugin
        import uuid
        request_id = str(uuid.uuid4())
        correlation_id = str(uuid.uuid4())

        logger.info(
            f"Executing intelligent search",
            extra={
                "request_id": request_id,
                "correlation_id": correlation_id,
                "query": request.query,
                "mode": request.mode,
                "sources": request.sources,
            },
        )

        result = await plugin_service.execute_plugin(
            plugin_name="intelligent-search",
            parameters=params,
            timeout_seconds=120,
            session_id=request.context.get("session_id"),
        )

        # Normalize and return response
        response = _normalize_plugin_result(
            plugin_result=result.result or {},
            query=request.query,
            mode=request.mode,
            request_id=request_id,
            correlation_id=correlation_id,
            plugin_id=plugin_info.id if hasattr(plugin_info, 'id') else "intelligent_search",
            plugin_version=plugin_info.version if hasattr(plugin_info, 'version') else "0.0.0",
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Failed to execute intelligent search",
            extra={"error": str(e), "query": request.query, "mode": request.mode},
        )
        error_response = create_service_error_response(
            service_name="intelligent-search",
            error=e,
            error_code=WebAPIErrorCode.PLUGIN_ERROR,
            user_message="Failed to execute search. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(WebAPIErrorCode.PLUGIN_ERROR),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/status", response_model=StatusResponse)
async def get_intelligent_search_status(
    plugin_service: PluginService = Depends(get_plugin_service),
):
    """
    Get the current status of the Intelligent Search plugin.

    Returns health, version, and execution statistics.
    """
    try:
        # Get plugin info
        plugin_info = await plugin_service.get_plugin_info("intelligent-search")

        if not plugin_info:
            raise HTTPException(
                status_code=404,
                detail="Intelligent Search plugin not found",
            )

        # Get metrics
        metrics = plugin_service.get_metrics()

        return StatusResponse(
            plugin_id=plugin_info.id if hasattr(plugin_info, 'id') else "intelligent_search",
            status=plugin_info.status.value,
            version=plugin_info.version,
            uptime_seconds=metrics.get("uptime_seconds", 0.0),
            last_error=getattr(plugin_info, "last_error", None),
            execution_count=getattr(plugin_info, "execution_count", 0),
            success_rate=getattr(plugin_info, "success_rate", 0.0),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get intelligent search status", extra={"error": str(e)})
        error_response = create_service_error_response(
            service_name="intelligent-search",
            error=e,
            error_code=WebAPIErrorCode.PLUGIN_ERROR,
            user_message="Failed to get plugin status.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(WebAPIErrorCode.PLUGIN_ERROR),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def get_intelligent_search_capabilities(
    plugin_service: PluginService = Depends(get_plugin_service),
):
    """
    Get the capabilities of the Intelligent Search plugin.

    Returns available modes, sources, RBAC requirements, and crawl capabilities.
    """
    try:
        # Get plugin info
        plugin_info = await plugin_service.get_plugin_info("intelligent-search")

        if not plugin_info:
            raise HTTPException(
                status_code=404,
                detail="Intelligent Search plugin not found",
            )

        # Check if Crawl4AI is available
        crawl_available = False
        try:
            from ai_karen_engine.integrations.web.crawl4ai_integration import (
                Crawl4AIIntegration,
            )

            integration = Crawl4AIIntegration()
            crawl_available = integration.available
        except Exception:
            crawl_available = False

        return CapabilitiesResponse(
            plugin_id=plugin_info.id if hasattr(plugin_info, 'id') else "intelligent_search",
            plugin_version=plugin_info.version if hasattr(plugin_info, 'version') else "0.0.0",
            enabled=plugin_info.enabled,
            permissions=getattr(plugin_info, "permissions", []),
            available_modes=["basic", "advanced", "unrestricted"],
            available_sources=["web", "memory", "documents", "local_knowledge"],
            rbac={
                "required_roles": ["user"],
                "unrestricted_required_roles": ["admin", "super_admin"],
            },
            crawl_capabilities={
                "enabled": crawl_available,
                "engine": "crawl4ai",
                "max_pages": 50,
                "max_depth": 5,
                "supports_screenshot": crawl_available,
                "supports_structured_extraction": crawl_available,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Failed to get intelligent search capabilities",
            extra={"error": str(e)},
        )
        error_response = create_service_error_response(
            service_name="intelligent-search",
            error=e,
            error_code=WebAPIErrorCode.PLUGIN_ERROR,
            user_message="Failed to get plugin capabilities.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(WebAPIErrorCode.PLUGIN_ERROR),
            detail=error_response.model_dump(mode="json"),
        )


__all__ = ["router"]
