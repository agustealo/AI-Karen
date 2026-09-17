"""Thin plugin-store ingress over canonical plugin runtime truth.

The store does not own plugin discovery, lifecycle state, persistence, or
analytics. ``PluginService`` owns the live local plugin registry. Capabilities
that do not yet have a durable source of truth fail explicitly instead of
fabricating success or zero-valued telemetry.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, Field

from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.core.services.dependencies import get_plugin_service
from ai_karen_engine.services.audit.audit_logging import get_audit_logger
from ai_karen_engine.services.plugin_service import PluginService

logger = logging.getLogger(__name__)


class PluginCategory(str, Enum):
    PRODUCTIVITY = "productivity"
    COMMUNICATION = "communication"
    AUTOMATION = "automation"
    ANALYTICS = "analytics"
    UTILITIES = "utilities"
    DEVELOPMENT = "development"
    INTEGRATION = "integration"
    SECURITY = "security"
    AI_ML = "ai_ml"


class PluginSortOrder(str, Enum):
    POPULARITY = "popularity"
    NEWEST = "newest"
    NAME = "name"
    UPDATED = "updated"
    RATING = "rating"


class PluginSearchRequest(BaseModel):
    query: Optional[str] = Field(None, description="Search query string")
    category: Optional[PluginCategory] = Field(None, description="Filter by category")
    sort_by: PluginSortOrder = Field(
        PluginSortOrder.POPULARITY,
        description="Sort order",
    )
    page: int = Field(1, ge=1, description="Page number")
    per_page: int = Field(20, ge=1, le=100, description="Items per page")
    min_version: Optional[str] = Field(None, description="Minimum version")
    max_version: Optional[str] = Field(None, description="Maximum version")


class PluginInstallRequest(BaseModel):
    plugin_id: str = Field(..., min_length=1, description="Plugin identifier")
    version: Optional[str] = Field(None, description="Specific local version to enable")


class PluginRatingRequest(BaseModel):
    plugin_id: str = Field(..., min_length=1, description="Plugin identifier")
    rating: int = Field(..., ge=1, le=5, description="Rating (1-5)")
    review: str = Field(..., min_length=10, max_length=1000, description="Review text")


class PluginStoreStats(BaseModel):
    total_plugins: int
    active_plugins: int
    total_downloads: Optional[int] = None
    total_ratings: Optional[int] = None
    recent_updates: Optional[int] = None


router = APIRouter(prefix="/store", tags=["plugin-store"])


def _response_meta(request: Request) -> Dict[str, str]:
    correlation_id = request.headers.get("X-Correlation-Id", "unknown")
    request_id = request.headers.get("X-Request-Id", correlation_id)
    return {"request_id": request_id, "correlation_id": correlation_id}


def _audit_plugin_event(
    *,
    request: Request,
    current_user: Dict[str, Any],
    event_type: str,
    action: str,
    outcome: str,
    details: Dict[str, Any],
) -> None:
    meta = _response_meta(request)
    get_audit_logger().log_audit_event(
        {
            "event_type": event_type,
            "severity": "info" if outcome == "ok" else "warning",
            "message": action,
            "user_id": current_user.get("user_id"),
            "tenant_id": current_user.get("tenant_id"),
            "correlation_id": meta["correlation_id"],
            "metadata": {
                "action": action,
                "outcome": outcome,
                "request_id": meta["request_id"],
                **details,
            },
        }
    )


def _manifest(metadata: Dict[str, Any]) -> Any:
    manifest = metadata.get("manifest")
    if manifest is None:
        raise ValueError("Plugin registry entry is missing its canonical manifest")
    return manifest


def _dependencies(manifest: Any) -> List[str]:
    dependencies = getattr(manifest, "dependencies", None)
    if dependencies is None:
        return []

    values: List[str] = []
    for attribute in ("plugins", "extensions", "system_services"):
        raw = getattr(dependencies, attribute, None) or []
        values.extend(str(item) for item in raw)
    return values


def _marketplace_payload(manifest: Any) -> Dict[str, Any]:
    marketplace = getattr(manifest, "marketplace", None)
    if marketplace is None:
        return {}
    if hasattr(marketplace, "model_dump"):
        return marketplace.model_dump(mode="json", exclude_none=True)
    if isinstance(marketplace, dict):
        return dict(marketplace)
    return {}


def _plugin_payload(metadata: Dict[str, Any]) -> Dict[str, Any]:
    manifest = _manifest(metadata)
    marketplace = _marketplace_payload(manifest)
    runtime_status = str(metadata.get("status") or "unknown")
    installed = runtime_status in {"registered", "disabled"}
    dependencies = _dependencies(manifest)

    return {
        "id": str(manifest.name),
        "name": str(manifest.name),
        "display_name": str(getattr(manifest, "display_name", manifest.name)),
        "description": str(getattr(manifest, "description", "")),
        "author": str(getattr(manifest, "author", "")),
        "version": str(getattr(manifest, "version", "")),
        "status": "installed" if installed else "available",
        "runtime_status": runtime_status,
        "category": str(getattr(manifest, "category", "")) or None,
        "downloads": marketplace.get("downloads"),
        "rating": marketplace.get("rating"),
        "rating_count": marketplace.get("reviews_count"),
        "license": getattr(manifest, "license", None),
        "tags": list(getattr(manifest, "tags", None) or []),
        "documentation_url": marketplace.get("documentation_url"),
        "support_url": marketplace.get("support_url"),
        "compatibility": {
            "min_karen_version": getattr(manifest, "kari_min_version", None),
            "requirements": dependencies,
        },
        "dependencies": dependencies,
    }


def _parse_version(value: str, field_name: str) -> Version:
    try:
        return Version(value)
    except InvalidVersion as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} must be a valid version string",
        ) from exc


def _version_matches(plugin: Dict[str, Any], request: PluginSearchRequest) -> bool:
    plugin_version = _parse_version(str(plugin["version"]), "plugin version")
    if request.min_version and plugin_version < _parse_version(
        request.min_version,
        "min_version",
    ):
        return False
    if request.max_version and plugin_version > _parse_version(
        request.max_version,
        "max_version",
    ):
        return False
    return True


def _sort_plugins(
    plugins: List[Dict[str, Any]],
    order: PluginSortOrder,
) -> List[Dict[str, Any]]:
    if order == PluginSortOrder.NAME:
        return sorted(plugins, key=lambda item: str(item["display_name"]).casefold())
    if order == PluginSortOrder.RATING:
        return sorted(
            plugins,
            key=lambda item: float(item.get("rating") or 0.0),
            reverse=True,
        )
    if order == PluginSortOrder.POPULARITY:
        return sorted(
            plugins,
            key=lambda item: (
                int(item.get("downloads") or 0),
                float(item.get("rating") or 0.0),
            ),
            reverse=True,
        )

    timestamp_field = "published_at" if order == PluginSortOrder.NEWEST else "updated_at"

    def timestamp(item: Dict[str, Any]) -> float:
        marketplace = item.get("marketplace") or {}
        raw = marketplace.get(timestamp_field)
        if not raw:
            return 0.0
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            return 0.0

    return sorted(plugins, key=timestamp, reverse=True)


def _require_admin(current_user: Dict[str, Any]) -> None:
    if "admin" not in current_user.get("roles", []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )


def _unsupported(detail: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=detail,
    )


async def _catalog(plugin_service: PluginService) -> List[Dict[str, Any]]:
    metadata_items = await plugin_service.list_plugins()
    plugins: List[Dict[str, Any]] = []
    for metadata in metadata_items:
        try:
            payload = _plugin_payload(metadata)
            payload["marketplace"] = _marketplace_payload(_manifest(metadata))
            plugins.append(payload)
        except (TypeError, ValueError, AttributeError) as exc:
            logger.error("Skipping invalid canonical plugin metadata: %s", exc)
    return plugins


@router.get("/search", response_model=Dict[str, Any])
async def search_plugins_endpoint(
    http_request: Request,
    request: PluginSearchRequest = Depends(),
    plugin_service: PluginService = Depends(get_plugin_service),
) -> Dict[str, Any]:
    plugins = await _catalog(plugin_service)

    if request.query:
        query = request.query.casefold()
        plugins = [
            plugin
            for plugin in plugins
            if query in str(plugin["name"]).casefold()
            or query in str(plugin["display_name"]).casefold()
            or query in str(plugin["description"]).casefold()
            or any(query in str(tag).casefold() for tag in plugin.get("tags") or [])
        ]

    if request.category:
        plugins = [
            plugin
            for plugin in plugins
            if str(plugin.get("category") or "").casefold()
            == request.category.value.casefold()
        ]

    if request.min_version or request.max_version:
        plugins = [plugin for plugin in plugins if _version_matches(plugin, request)]

    plugins = _sort_plugins(plugins, request.sort_by)
    offset = (request.page - 1) * request.per_page
    page_plugins = plugins[offset : offset + request.per_page]

    for plugin in page_plugins:
        plugin.pop("marketplace", None)

    return {
        "plugins": page_plugins,
        "total": len(plugins),
        "page": request.page,
        "per_page": request.per_page,
        "total_pages": (len(plugins) + request.per_page - 1) // request.per_page,
        "has_next": offset + request.per_page < len(plugins),
        **_response_meta(http_request),
    }


@router.get("/plugins/{plugin_id}", response_model=Dict[str, Any])
async def get_plugin_details_endpoint(
    plugin_id: str,
    plugin_service: PluginService = Depends(get_plugin_service),
) -> Dict[str, Any]:
    metadata = await plugin_service.get_plugin_info(plugin_id)
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin {plugin_id} not found",
        )

    plugin = _plugin_payload(metadata)
    marketplace = _marketplace_payload(_manifest(metadata))
    return {
        "plugin": plugin,
        "marketplace_info": marketplace or None,
        "analytics": None,
        "installed": plugin["status"] == "installed",
        "update_available": None,
    }


@router.post("/install", response_model=Dict[str, Any])
async def install_plugin_endpoint(
    http_request: Request,
    request: PluginInstallRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
    plugin_service: PluginService = Depends(get_plugin_service),
) -> Dict[str, Any]:
    _require_admin(current_user)

    metadata = await plugin_service.get_plugin_info(request.plugin_id)
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin {request.plugin_id} not found in the local catalog",
        )

    plugin = _plugin_payload(metadata)
    actual_version = str(plugin["version"])
    if request.version and request.version != actual_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Requested version {request.version} is not present in the local catalog; "
                f"available version is {actual_version}"
            ),
        )

    success = await plugin_service.enable_plugin(request.plugin_id)
    _audit_plugin_event(
        request=http_request,
        current_user=current_user,
        event_type="plugin_install",
        action="enable_local_catalog_plugin",
        outcome="ok" if success else "error",
        details={"plugin_id": request.plugin_id, "version": actual_version},
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Plugin {request.plugin_id} could not be enabled",
        )

    return {
        "success": True,
        "message": f"Plugin '{request.plugin_id}' enabled from the local catalog",
        "plugin_id": request.plugin_id,
        "version": actual_version,
        "operation": "enable_local_catalog_plugin",
        **_response_meta(http_request),
    }


@router.post("/rate", response_model=Dict[str, Any])
async def rate_plugin_endpoint(
    http_request: Request,
    request: PluginRatingRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_admin(current_user)
    _audit_plugin_event(
        request=http_request,
        current_user=current_user,
        event_type="plugin_rate",
        action="rate",
        outcome="unavailable",
        details={
            "plugin_id": request.plugin_id,
            "reason": "durable_plugin_rating_store_not_configured",
        },
    )
    _unsupported("Plugin ratings are unavailable until a durable rating store is configured")


@router.get("/statistics", response_model=PluginStoreStats)
async def get_statistics_endpoint(
    plugin_service: PluginService = Depends(get_plugin_service),
) -> PluginStoreStats:
    plugins = await _catalog(plugin_service)
    active_count = sum(1 for plugin in plugins if plugin["status"] == "installed")
    return PluginStoreStats(
        total_plugins=len(plugins),
        active_plugins=active_count,
        total_downloads=None,
        total_ratings=None,
        recent_updates=None,
    )


@router.get("/categories", response_model=List[Dict[str, Any]])
async def get_categories_endpoint(
    plugin_service: PluginService = Depends(get_plugin_service),
) -> List[Dict[str, Any]]:
    plugins = await _catalog(plugin_service)
    counts: Dict[str, int] = {}
    for plugin in plugins:
        category = str(plugin.get("category") or "uncategorized")
        counts[category] = counts.get(category, 0) + 1
    return [
        {
            "name": category,
            "display_name": category.replace("_", " ").title(),
            "plugin_count": count,
        }
        for category, count in sorted(counts.items())
    ]


@router.get("/trending", response_model=List[Dict[str, Any]])
async def get_trending_endpoint(
    limit: int = Query(10, ge=1, le=50),
) -> List[Dict[str, Any]]:
    del limit
    _unsupported(
        "Trending plugins are unavailable until canonical marketplace analytics are configured"
    )


@router.get("/updates", response_model=List[Dict[str, Any]])
async def get_updates_endpoint(
    http_request: Request,
    plugin_ids: Optional[List[str]] = Query(None),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    _require_admin(current_user)
    _audit_plugin_event(
        request=http_request,
        current_user=current_user,
        event_type="plugin_update_check",
        action="updates",
        outcome="unavailable",
        details={
            "plugin_ids": plugin_ids or [],
            "reason": "canonical_update_feed_not_configured",
        },
    )
    _unsupported(
        "Plugin update checks are unavailable until a canonical update feed is configured"
    )
