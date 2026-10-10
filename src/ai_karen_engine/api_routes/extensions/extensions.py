"""Extension management API routes."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ai_karen_engine.utils.dependency_checks import import_fastapi

if TYPE_CHECKING:
    from fastapi import APIRouter, Depends, HTTPException, Request
else:
    APIRouter, Depends, HTTPException, Request = import_fastapi(
        "APIRouter", "Depends", "HTTPException", "Request"
    )

logger = logging.getLogger(__name__)

_initialized_managers: Set[int] = set()
_initializing_managers: Set[int] = set()


async def _async_init_manager(manager: Any) -> None:
    manager_id = id(manager)
    try:
        await manager.initialize()
        _initialized_managers.add(manager_id)
    except Exception as e:
        logger.warning(f"Failed to initialize extension manager: {e}")
    finally:
        _initializing_managers.discard(manager_id)


def get_extension_manager():
    """Get extension manager, returns None if not available."""
    try:
        from ai_karen_engine.extensions.platform.core.manager import (
            get_extension_core_manager as get_manager,
        )

        manager = get_manager()
        manager_id = id(manager)

        if manager_id in _initialized_managers:
            return manager

        try:
            loop = asyncio.get_running_loop()
            _initializing_managers.add(manager_id)
            loop.create_task(_async_init_manager(manager))
        except RuntimeError:
            asyncio.run(manager.initialize())
            _initialized_managers.add(manager_id)
        except Exception as e:
            logger.warning(f"Failed to initialize extension manager: {e}")

        return manager
    except ImportError as e:
        logger.error(f"Extension system not available: {e}")
        return None


# Define the API model for status
class ExtensionStatusAPI(BaseModel):
    id: str
    name: str
    display_name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    version: str
    status: str
    loaded_at: datetime | None = Field(default=None)
    error_message: str | None = Field(default=None)
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    menu_contributions: List[Dict[str, Any]] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    purpose: str | None = Field(default=None)
    category: str = Field(default="integration")
    has_component: bool = Field(default=False)
    rbac: Dict[str, Any] = Field(default_factory=dict)


# Pydantic model for install request
class InstallRequest(BaseModel):
    plugin_id: str


router = APIRouter()

# Import authentication dependencies with auth bypass support
_real_get_current_user = None
auth_config = None
try:
    from ai_karen_engine.auth.auth_middleware import (
        AuthenticationError,
        get_current_user as _real_get_current_user,
    )
    from ai_karen_engine.core.security.auth_config import auth_config

    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    AuthenticationError = Exception


async def get_current_user(request: Request):
    """Get current user with auth bypass support."""
    if not AUTH_AVAILABLE:
        return {"user_id": "guest", "authenticated": False}

    state_user = getattr(request.state, "user", None)
    if isinstance(state_user, dict):
        return state_user

    if (
        auth_config
        and hasattr(auth_config, "should_bypass_auth")
        and auth_config.should_bypass_auth()
    ):
        context = auth_config.get_dev_user_context()
        return context


    if _real_get_current_user:
        try:
            return await _real_get_current_user(request)
        except Exception:
            return {"user_id": "guest", "authenticated": False}
    return {"user_id": "guest", "authenticated": False}




async def require_extension_catalog_access(request: Request) -> dict[str, Any]:
    """Authenticate and authorize catalog reads through canonical RBAC."""
    user = await get_current_user(request)
    if (
        not isinstance(user, dict)
        or user.get("authenticated") is False
        or not user.get("user_id")
        or user.get("user_id") == "guest"
        or not user.get("tenant_id")
    ):
        raise HTTPException(status_code=401, detail="Authentication required")

    from ai_karen_engine.auth.rbac_middleware import Permission, RBACManager

    rbac = RBACManager()
    granted = rbac.has_permission(user, Permission.READ)
    rbac.audit_access_attempt(
        user,
        Permission.READ,
        "extension_catalog",
        granted,
        request=request,
    )
    if not granted:
        raise HTTPException(status_code=403, detail="Extension catalog access denied")
    return user

async def require_extension_mutation_access(request: Request) -> dict[str, Any]:
    """Require authenticated tenant administrator permission for lifecycle writes."""
    user = await get_current_user(request)
    if (
        not isinstance(user, dict)
        or user.get("authenticated") is False
        or not user.get("user_id")
        or user.get("user_id") == "guest"
        or not user.get("tenant_id")
    ):
        raise HTTPException(status_code=401, detail="Authentication required")
    from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager

    rbac = get_rbac_manager()
    allowed = rbac.has_permission(user, Permission.ADMIN_PLUGINS_MANAGE)
    rbac.audit_access_attempt(
        user,
        Permission.ADMIN_PLUGINS_MANAGE,
        "extension_lifecycle",
        allowed,
        request=request,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Plugin management access denied")
    return user


@router.get("/", response_model=List[ExtensionStatusAPI])
async def list_extensions_root(user: dict[str, Any] = Depends(require_extension_catalog_access)):
    """List all extensions and their status (root endpoint)."""
    manager = get_extension_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Extension catalog unavailable")
    try:
        return await manager.refresh_extensions(user_context=user)
    except Exception:
        logger.exception("Extension catalog refresh failed")
        raise HTTPException(status_code=503, detail="Extension catalog unavailable")


@router.get("/list", response_model=List[ExtensionStatusAPI])
async def list_extensions(user: dict[str, Any] = Depends(require_extension_catalog_access)):
    """List all extensions and their status."""
    manager = get_extension_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Extension catalog unavailable")
    try:
        return await manager.refresh_extensions(user_context=user)
    except Exception:
        logger.exception("Extension catalog refresh failed")
        raise HTTPException(status_code=503, detail="Extension catalog unavailable")


@router.post("/install")
async def install_extension(request: InstallRequest, user: dict[str, Any] = Depends(require_extension_mutation_access)):
    """Extension installation endpoint."""
    manager = get_extension_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Extension manager not initialized")

    try:
        from ai_karen_engine.extensions.platform.core.registry.ui_installer import (
            install_ui,
        )

        result = install_ui(request.plugin_id, "integration")
        return {
            "success": result.status.value == "success",
            "message": result.message,
            "plugin_id": request.plugin_id,
        }
    except Exception as e:
        logger.error(f"Error during UI installation for {request.plugin_id}: {e}")
        return {"success": False, "message": str(e), "plugin_id": request.plugin_id}


@router.get("/{extension_name}")
async def get_extension_status(extension_name: str, user: dict[str, Any] = Depends(require_extension_catalog_access)):
    """Get detailed status of a specific extension."""
    manager = get_extension_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Extension manager not initialized")

    status = manager.get_extension_status(extension_name)
    if not status:
        await manager.refresh_extensions()
        status = manager.get_extension_status(extension_name)
    if not status:
        raise HTTPException(status_code=404, detail="Extension not found")
    return status


@router.get("/debug/system-status")
async def get_extension_system_status(user: dict[str, Any] = Depends(require_extension_mutation_access)):
    """Debug endpoint to check extension system status."""
    try:
        manager = get_extension_manager()
        if not manager:
            return {
                "status": "error",
                "message": "Extension manager not available",
                "manager": None,
                "registry": None,
                "discovery": None,
            }

        # Check registry status
        registry_status = {
            "discovered_count": len(manager.registry.list_discovered()),
            "loaded_count": len(manager.registry.list_extensions()),
            "discovered": manager.registry.list_discovered(),
        }

        # Check health summary
        health_summary = manager.health_summary()

        return {
            "status": "ok",
            "manager": {
                "initialized": hasattr(manager, "_initialized"),
                "extensions_dir": str(manager.extensions_dir),
            },
            "registry": registry_status,
            "health": health_summary,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "timestamp": datetime.now().isoformat(),
        }


@router.post("/{extension_name}/load")
async def load_extension(extension_name: str, user=Depends(require_extension_mutation_access)):
    """Load an extension."""
    manager = get_extension_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Extension manager not initialized")
    try:
        record = await manager.load_extension(extension_name)
        if record is None:
            raise HTTPException(
                status_code=409,
                detail="Extension could not be enabled by the canonical runtime",
            )
        await manager.refresh_extensions()
        return {
            "success": True,
            "message": f"Extension {extension_name} loaded",
            "plugin_id": extension_name,
            "status": (record.get("status", "loaded") if isinstance(record, dict) else getattr(getattr(record, "status", None), "value", "loaded")) if record else "loaded",
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Extension enable failed")
        raise HTTPException(status_code=503, detail="Extension enable failed")


@router.post("/{extension_name}/unload")
async def unload_extension(extension_name: str, user=Depends(require_extension_mutation_access)):
    """Unload an extension."""
    manager = get_extension_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Extension manager not initialized")
    try:
        success = await manager.unload_extension(extension_name)
        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"Extension {extension_name} is not currently loaded",
            )
        await manager.refresh_extensions()
        return {
            "success": True,
            "message": f"Extension {extension_name} unloaded",
            "plugin_id": extension_name,
            "status": "unloaded",
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{extension_name}/remove-ui")
async def remove_extension_ui(extension_name: str, user=Depends(require_extension_mutation_access)):
    """Remove the installed UI package for an extension."""
    try:
        from ai_karen_engine.extensions.platform.core.registry.ui_installer import (
            remove_ui,
        )

        result = remove_ui(extension_name)
        manager = get_extension_manager()
        if manager:
            await manager.refresh_extensions()
        return {
            "success": result.status.value == "success"
            or result.status.value == "not_found",
            "message": result.message,
            "plugin_id": extension_name,
            "status": result.status.value,
        }
    except Exception as e:
        logger.error(f"Error removing UI for {extension_name}: {e}")
        raise HTTPException(status_code=400, detail=str(e))


__all__ = ["router"]
