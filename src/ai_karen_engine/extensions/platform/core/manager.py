"""Compatibility facade over the canonical plugin service.

Catalog discovery remains owned by the platform registry used by ``PluginKernel``.
This module no longer owns loading, execution, routing, or a second runtime
registry. Existing callers may continue to use the historical manager surface,
but all state changes are delegated to the one canonical ``PluginService``.

The PluginService accessors are intentionally imported lazily. ``PluginKernel``
loads platform catalog modules while PluginService itself imports PluginKernel,
so an import-time dependency in this facade would create a package cycle.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ai_karen_engine.services.plugin_service import PluginService

logger = logging.getLogger(__name__)


def get_plugin_service() -> "PluginService":
    """Resolve the canonical service lazily to keep platform imports acyclic."""
    from ai_karen_engine.services.plugin_service import get_plugin_service as _get

    return _get()


async def initialize_plugin_service(**kwargs: Any) -> "PluginService":
    """Initialize the canonical service without an import-time kernel back-edge."""
    from ai_karen_engine.services.plugin_service import (
        initialize_plugin_service as _initialize,
    )

    return await _initialize(**kwargs)


@dataclass
class ExtensionCoreManager:
    """Read/catalog facade backed by the canonical plugin runtime."""

    extensions_dir: str = "src/ai_karen_engine/extensions/plugins"

    def __post_init__(self) -> None:
        self._root = Path(self.extensions_dir)

    def _service(self) -> "PluginService":
        service = get_plugin_service()
        if service.initialized:
            active_root = Path(
                service.core_plugins_path
                or service.marketplace_path
                or "src/ai_karen_engine/extensions/plugins"
            )
            if active_root.resolve() != self._root.resolve():
                raise RuntimeError(
                    "ExtensionCoreManager root does not match the initialized PluginService"
                )
        return service

    async def _ensure_service(self) -> "PluginService":
        service = self._service()
        if service.initialized:
            return service
        return await initialize_plugin_service(
            marketplace_path=self._root,
            core_plugins_path=self._root,
            auto_discover=True,
        )

    @staticmethod
    def _extension_capabilities(manifest: Any) -> Dict[str, bool]:
        capabilities = getattr(manifest, "capabilities", manifest)
        return {
            "provides_ui": bool(getattr(capabilities, "provides_ui", False)),
            "provides_api": bool(getattr(capabilities, "provides_api", False)),
            "provides_background_tasks": bool(
                getattr(capabilities, "provides_background_tasks", False)
            ),
            "provides_webhooks": bool(
                getattr(capabilities, "provides_webhooks", False)
            ),
        }

    @classmethod
    def _status_from_record(cls, record: Dict[str, Any]) -> Dict[str, Any]:
        manifest = record.get("manifest")
        if manifest is None:
            raise ValueError("Plugin catalog record is missing its manifest")
        return {
            "id": manifest.name,
            "name": manifest.name,
            "display_name": getattr(manifest, "display_name", None) or manifest.name,
            "description": getattr(manifest, "description", None)
            or "No description available",
            "version": manifest.version,
            "status": str(record.get("status") or "unknown"),
            "loaded_at": None,
            "error_message": record.get("error_message"),
            "capabilities": cls._extension_capabilities(manifest),
            "menu_contributions": list(
                getattr(getattr(manifest, "ui", None), "menu_contributions", []) or []
            ),
        }

    async def refresh_registry(self) -> Dict[str, Any]:
        service = await self._ensure_service()
        await service.refresh_plugins()
        records = await service.list_plugins()
        return {
            "discovered_count": len(records),
            "discovered": [record["manifest"].name for record in records],
        }

    def list_extension_statuses(self) -> List[Dict[str, Any]]:
        service = self._service()
        if not service.initialized or service.kernel is None:
            return []
        return [
            self._status_from_record(record)
            for record in service.kernel.list_records()
        ]

    def get_extension_status(self, extension_name: str) -> Optional[Dict[str, Any]]:
        service = self._service()
        record = service.get_plugin(extension_name)
        return self._status_from_record(record) if record is not None else None

    async def reload_runtime(self) -> Dict[str, Any]:
        service = await self._ensure_service()
        discovered_count = await service.refresh_plugins()
        enabled = await service.list_plugins(enabled_only=True)
        return {
            "discovered_count": discovered_count,
            "loaded_count": len(enabled),
        }

    async def initialize(self) -> Dict[str, Any]:
        """Initialize the canonical service without importing plugin code."""
        await self._ensure_service()
        logger.info("Canonical plugin service initialized through platform facade")
        return self.health_summary()

    async def load_extension(self, extension_name: str) -> Optional[Dict[str, Any]]:
        """Compatibility name: enable a plugin without eagerly importing its code."""
        service = await self._ensure_service()
        if not await service.enable_plugin(extension_name):
            return None
        record = await service.get_plugin_info(extension_name)
        return self._status_from_record(record) if record is not None else None

    async def unload_extension(self, extension_name: str) -> bool:
        """Compatibility name: disable a plugin in the canonical runtime."""
        service = await self._ensure_service()
        return await service.disable_plugin(extension_name)

    async def reload_extension(self, extension_name: str) -> Optional[Dict[str, Any]]:
        service = await self._ensure_service()
        await service.refresh_plugins()
        if not await service.enable_plugin(extension_name):
            return None
        record = await service.get_plugin_info(extension_name)
        return self._status_from_record(record) if record is not None else None

    async def discover_extensions(self) -> List[Dict[str, Any]]:
        service = await self._ensure_service()
        return [
            self._status_from_record(record)
            for record in await service.list_plugins()
        ]

    async def refresh_extensions(self) -> List[Dict[str, Any]]:
        service = await self._ensure_service()
        await service.refresh_plugins()
        return [
            self._status_from_record(record)
            for record in await service.list_plugins()
        ]

    def health_summary(self) -> Dict[str, Any]:
        service = self._service()
        stats = service.get_service_stats()
        if not stats.get("initialized"):
            return {
                "registry": {"discovered_count": 0, "loaded_count": 0},
                "integration": {
                    "status": "initializing",
                    "authority": "PluginService",
                },
            }
        registry = stats.get("registry_stats", {})
        by_status = registry.get("by_status", {})
        enabled_count = sum(
            int(by_status.get(state, 0) or 0)
            for state in ("registered", "enabled", "loaded", "active")
        )
        return {
            "registry": {
                "discovered_count": int(registry.get("total_plugins", 0) or 0),
                "loaded_count": enabled_count,
            },
            "integration": {
                "status": "healthy",
                "authority": "PluginService",
            },
        }


_core_manager: ExtensionCoreManager | None = None


def get_extension_core_manager() -> ExtensionCoreManager:
    global _core_manager
    if _core_manager is None:
        _core_manager = ExtensionCoreManager()
    return _core_manager


PluginManager = ExtensionCoreManager
