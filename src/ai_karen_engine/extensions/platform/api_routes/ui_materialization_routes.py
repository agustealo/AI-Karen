"""Thin UI materialization API routes backed by governed extension services.

The API layer does not discover plugins independently, infer plugin health,
assume RBAC, invent versions/capabilities, or inspect installation paths. It
translates canonical registry/materialization/installer state for UI clients.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from ai_karen_engine.extensions.platform.core.registry.ui_installer import get_ui_service
from ai_karen_engine.extensions.platform.core.registry.ui_materialization import (
    get_ui_pipeline,
)

logger = logging.getLogger("kari.ui_materialization_routes")

router = APIRouter(prefix="/api/ui-materialization", tags=["ui-materialization"])


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _capabilities_to_dict(metadata: Any) -> Dict[str, Any]:
    capabilities = getattr(metadata, "capabilities", None)
    if capabilities is None:
        return {}

    model_dump = getattr(capabilities, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump())

    as_dict = getattr(capabilities, "dict", None)
    if callable(as_dict):
        return dict(as_dict())

    if hasattr(capabilities, "__dict__"):
        return {
            key: _enum_value(value)
            for key, value in vars(capabilities).items()
            if not key.startswith("_")
        }

    return {}


def _get_registry_metadata(ui_service: Any, plugin_id: str) -> Any:
    registry = getattr(ui_service, "registry", None)
    get_metadata = getattr(registry, "get_metadata", None)
    if not callable(get_metadata):
        raise HTTPException(
            status_code=503,
            detail="Extension registry metadata is unavailable; UI state cannot be inferred.",
        )

    metadata = get_metadata(plugin_id)
    if metadata is None:
        raise HTTPException(
            status_code=404,
            detail=f"Plugin '{plugin_id}' is not present in the governed extension registry.",
        )

    return metadata


def _install_plugin_ui_authoritatively(plugin_id: str) -> Dict[str, Any]:
    """Install UI using category and validation state from the extension registry."""

    ui_service = get_ui_service()
    metadata = _get_registry_metadata(ui_service, plugin_id)

    if not bool(getattr(metadata, "is_valid", False)):
        errors = list(getattr(metadata, "validation_errors", []) or [])
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Plugin registry metadata is not valid for UI installation.",
                "plugin_id": plugin_id,
                "validation_errors": errors,
            },
        )

    category = getattr(metadata, "category", None)
    if not category:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Plugin registry metadata does not declare a category.",
                "plugin_id": plugin_id,
            },
        )

    result = ui_service.install_ui(plugin_id, str(category))
    result_status = _enum_value(result.status)
    result_state = _enum_value(result.state)

    if result_status != "success":
        status_code = 404 if result_status == "not_found" else 409
        raise HTTPException(
            status_code=status_code,
            detail={
                "message": result.message,
                "plugin_id": plugin_id,
                "install_status": result_status,
                "state": result_state,
                "error_code": getattr(result, "error_code", None),
                "details": getattr(result, "details", None),
            },
        )

    return {
        "status": "success",
        "data": {
            "plugin_id": plugin_id,
            "install_status": result_status,
            "state": result_state,
            "message": result.message,
            "details": getattr(result, "details", None),
        },
    }


def _build_installed_ui_contract(ui_service: Any) -> list[Dict[str, Any]]:
    """Project installer + registry truth into a stable presentation contract.

    Missing registry metadata remains missing. In particular, this function does
    not manufacture active status, semantic version, capabilities, UI presence,
    RBAC grants, or authorization decisions.
    """

    plugins: list[Dict[str, Any]] = []
    registry = getattr(ui_service, "registry", None)
    get_metadata = getattr(registry, "get_metadata", None)

    for item in ui_service.list_installed_ui():
        plugin_id = str(item["plugin_id"])
        metadata = get_metadata(plugin_id) if callable(get_metadata) else None
        metadata_valid = bool(metadata and getattr(metadata, "is_valid", False))

        plugin = {
            "plugin_id": plugin_id,
            "name": getattr(metadata, "name", None) or plugin_id,
            "display_name": getattr(metadata, "display_name", None) or plugin_id,
            "description": getattr(metadata, "description", None) if metadata else None,
            "version": getattr(metadata, "version", None) if metadata else None,
            "category": getattr(metadata, "category", None) if metadata else None,
            "status": item.get("state"),
            "install_status": item.get("status"),
            "message": item.get("message"),
            "details": item.get("details") or {},
            "capabilities": _capabilities_to_dict(metadata) if metadata else {},
            "ui": {},
            "rbac": {},
            "tags": list(getattr(metadata, "tags", []) or []) if metadata else [],
            "purpose": None,
            "manifest_valid": metadata_valid,
            "validation_errors": list(
                getattr(metadata, "validation_errors", []) or []
            )
            if metadata
            else ["registry_metadata_unavailable"],
            "authorized": False,
            "authorization_status": "not_evaluated",
        }
        plugins.append(plugin)

    return plugins


@router.get("/status", response_model=Dict[str, Any])
async def get_materialization_status():
    """Return canonical materialization artifact status."""

    try:
        status = await get_ui_pipeline().get_artifact_status()
        return {"status": "success", "data": status}
    except Exception as exc:
        logger.exception("Failed to get UI materialization status")
        raise HTTPException(
            status_code=500,
            detail="Failed to get UI materialization status.",
        ) from exc


@router.post("/discover", response_model=Dict[str, Any])
async def discover_ui_plugins():
    """Return UI-capable plugins discovered by the governed materialization service."""

    try:
        plugins = await get_ui_pipeline().discover_ui_plugins()
        return {
            "status": "success",
            "data": {"plugins": plugins, "total": len(plugins)},
        }
    except Exception as exc:
        logger.exception("Failed to discover governed UI plugins")
        raise HTTPException(
            status_code=500,
            detail="Failed to discover UI plugins.",
        ) from exc


@router.post("/materialize", response_model=Dict[str, Any])
async def materialize_all_artifacts():
    """Delegate full materialization to the canonical pipeline."""

    try:
        result = await get_ui_pipeline().materialize_all()
        return {"status": "success", "data": result}
    except Exception as exc:
        logger.exception("Failed to materialize UI artifacts")
        raise HTTPException(
            status_code=500,
            detail="Failed to materialize UI artifacts.",
        ) from exc


@router.post("/materialize/{plugin_id}", response_model=Dict[str, Any])
async def materialize_plugin_artifacts(plugin_id: str):
    """Install a plugin UI only when canonical installer state requires it."""

    ui_service = get_ui_service()
    current_state = ui_service.get_ui_state(plugin_id)
    state = current_state.get("state")
    install_status = current_state.get("status")

    if state == "installed" and install_status == "success":
        return {
            "status": "success",
            "data": {
                "plugin_id": plugin_id,
                "state": state,
                "install_status": install_status,
                "message": current_state.get("message"),
                "details": current_state.get("details") or {},
            },
        }

    if state == "installed":
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Installed UI failed canonical validation.",
                "plugin_id": plugin_id,
                "state": state,
                "install_status": install_status,
                "details": current_state.get("details") or {},
            },
        )

    return _install_plugin_ui_authoritatively(plugin_id)


@router.post("/install/{plugin_id}", response_model=Dict[str, Any])
async def install_plugin_ui(plugin_id: str):
    """Delegate installation using registry-owned plugin metadata."""

    return _install_plugin_ui_authoritatively(plugin_id)


@router.get("/installed", response_model=Dict[str, Any])
async def list_installed_ui_plugins():
    """Return installed UI state without fabricating backend/plugin truth."""

    try:
        plugins = _build_installed_ui_contract(get_ui_service())
        return {
            "status": "success",
            "data": {"plugins": plugins, "total": len(plugins)},
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to list installed UI plugins")
        raise HTTPException(
            status_code=500,
            detail="Failed to list installed UI plugins.",
        ) from exc


@router.get("/import-map", response_model=Dict[str, Any])
async def get_import_map():
    """Return the import map generated from governed UI discovery."""

    try:
        pipeline = get_ui_pipeline()
        ui_plugins = await pipeline.discover_ui_plugins()
        import_map = await pipeline.generate_import_map(ui_plugins)
        return {
            "status": "success",
            "data": {
                "import_map": import_map,
                "total_entries": len(import_map),
            },
        }
    except Exception as exc:
        logger.exception("Failed to generate UI import map")
        raise HTTPException(
            status_code=500,
            detail="Failed to generate UI import map.",
        ) from exc


@router.post("/cleanup", response_model=Dict[str, Any])
async def cleanup_stale_artifacts():
    """Delegate stale artifact cleanup to the materialization pipeline."""

    try:
        pipeline = get_ui_pipeline()
        ui_plugins = await pipeline.discover_ui_plugins()
        removed = await pipeline.cleanup_stale_artifacts(ui_plugins)
        return {
            "status": "success",
            "data": {"removed_count": len(removed), "removed": removed},
        }
    except Exception as exc:
        logger.exception("Failed to clean stale UI artifacts")
        raise HTTPException(
            status_code=500,
            detail="Failed to clean stale UI artifacts.",
        ) from exc


@router.get("/plugin/{plugin_id}", response_model=Dict[str, Any])
async def get_plugin_ui_status(plugin_id: str):
    """Return materializer-owned UI metadata for one plugin."""

    try:
        ui_plugins = await get_ui_pipeline().discover_ui_plugins()
        plugin_ui = next(
            (plugin for plugin in ui_plugins if plugin.get("plugin_id") == plugin_id),
            None,
        )
        if plugin_ui is None:
            raise HTTPException(
                status_code=404,
                detail=f"Plugin '{plugin_id}' is not a governed UI-capable plugin.",
            )
        return {"status": "success", "data": plugin_ui}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to get UI status for plugin %s", plugin_id)
        raise HTTPException(
            status_code=500,
            detail="Failed to get plugin UI status.",
        ) from exc


@router.get("/icons/{plugin_id}", response_model=Dict[str, Any])
async def get_plugin_icons(plugin_id: str):
    """Return icons discovered by the canonical materialization pipeline."""

    try:
        ui_plugins = await get_ui_pipeline().discover_ui_plugins()
        plugin_ui = next(
            (plugin for plugin in ui_plugins if plugin.get("plugin_id") == plugin_id),
            None,
        )
        if plugin_ui is None:
            raise HTTPException(
                status_code=404,
                detail=f"Plugin '{plugin_id}' is not a governed UI-capable plugin.",
            )

        icons = plugin_ui.get("icons", [])
        return {
            "status": "success",
            "data": {"plugin_id": plugin_id, "icons": icons, "total": len(icons)},
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to get UI icons for plugin %s", plugin_id)
        raise HTTPException(
            status_code=500,
            detail="Failed to get plugin UI icons.",
        ) from exc
