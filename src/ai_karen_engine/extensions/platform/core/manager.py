"""Catalog/application facade for the canonical extension kernel.

The platform layer may expose catalog metadata and workflow coordination, but it
must not construct a second loader, router, registry, lifecycle engine, or
executor. Runtime truth is projected from the global ``PluginService``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ai_karen_engine.extensions.platform.core.integration.manager import get_plugin_manager
from ai_karen_engine.extensions.platform.core.integration.orchestrator import (
    get_plugin_orchestrator,
)
from ai_karen_engine.services.plugin_service import PluginService, get_plugin_service

logger = logging.getLogger(__name__)
_ENABLED_STATES = {"registered", "enabled", "loaded", "active"}


@dataclass
class ExtensionCoreManager:
    """Platform facade over one canonical plugin service/kernel."""

    extensions_dir: str = "src/ai_karen_engine/extensions/plugins"

    def __post_init__(self) -> None:
        self.integration = get_plugin_manager()
        self.orchestrator = get_plugin_orchestrator()

    @property
    def service(self) -> PluginService:
        return get_plugin_service()

    @property
    def registry(self) -> Any:
        """Expose the kernel's catalog registry for read-only compatibility."""
        service = self.service
        if not service.initialized or service.kernel is None:
            return None
        return service.kernel.catalog_registry

    async def _ensure_service(self) -> PluginService:
        service = self.service
        if not service.initialized:
            await service.initialize(auto_discover=True)
        return service

    async def refresh_registry(self) -> Dict[str, Any]:
        service = await self._ensure_service()
        records = await service.discover_plugins(force_refresh=True)
        return {
            "discovered_count": len(records),
            "discovered": sorted(records),
        }

    @staticmethod
    def _extension_capabilities(source: Any) -> Dict[str, bool]:
        return {
            "provides_ui": bool(getattr(source, "provides_ui", False)),
            "provides_api": bool(getattr(source, "provides_api", False)),
            "provides_background_tasks": bool(
                getattr(source, "provides_background_tasks", False)
            ),
            "provides_webhooks": bool(getattr(source, "provides_webhooks", False)),
        }

    def _build_extension_status(self, extension_name: str) -> Dict[str, Any] | None:
        record = self.service.get_plugin(extension_name)
        if record is None:
            return None
        manifest = record.get("manifest")
        if manifest is None:
            return None
        status = str(record.get("status") or "unknown")
        return {
            "id": str(getattr(manifest, "name", extension_name)),
            "name": str(getattr(manifest, "name", extension_name)),
            "display_name": getattr(manifest, "display_name", None)
            or str(getattr(manifest, "name", extension_name)),
            "description": getattr(manifest, "description", None)
            or "No description available",
            "version": str(getattr(manifest, "version", "")),
            "status": status,
            "loaded_at": None,
            "error_message": record.get("error_message"),
            "capabilities": self._extension_capabilities(
                getattr(manifest, "capabilities", manifest)
            ),
            "menu_contributions": list(
                getattr(manifest, "menu_contributions", []) or []
            ),
        }

    def list_extension_statuses(self) -> List[Dict[str, Any]]:
        service = self.service
        if not service.initialized or service.kernel is None:
            return []
        items = [
            self._build_extension_status(
                str(getattr(record.get("manifest"), "name", ""))
            )
            for record in service.kernel.list_records()
            if getattr(record.get("manifest"), "name", None)
        ]
        return [item for item in items if item is not None]

    def get_extension_status(self, extension_name: str) -> Dict[str, Any] | None:
        return self._build_extension_status(extension_name)

    async def reload_runtime(self) -> Dict[str, Any]:
        service = await self._ensure_service()
        discovered_count = await service.refresh_plugins()
        stats = service.get_service_stats().get("registry_stats", {})
        status_counts = stats.get("by_status", {})
        return {
            "discovered_count": discovered_count,
            "enabled_count": sum(
                int(status_counts.get(state, 0) or 0) for state in _ENABLED_STATES
            ),
            "authority": "PluginKernel",
        }

    async def initialize(self) -> Dict[str, Any]:
        """Attach platform/catalog consumers to the canonical plugin runtime."""
        try:
            await self.integration.initialize()
            service = await self._ensure_service()
            stats = service.get_service_stats().get("registry_stats", {})
            logger.info(
                "Extension platform attached to canonical kernel: %d catalog plugins",
                int(stats.get("total_plugins", 0) or 0),
            )
            return self.health_summary()
        except Exception:
            logger.exception("Failed to attach extension platform to canonical kernel")
            raise

    async def load_extension(self, extension_name: str) -> Optional[Dict[str, Any]]:
        """Compatibility name: enable execution without eager code import."""
        service = await self._ensure_service()
        if await service.get_plugin_info(extension_name) is None:
            return None
        if not await service.enable_plugin(extension_name):
            return None
        return await service.get_plugin_info(extension_name)

    async def unload_extension(self, extension_name: str) -> bool:
        service = await self._ensure_service()
        return await service.disable_plugin(extension_name)

    async def reload_extension(self, extension_name: str) -> Optional[Dict[str, Any]]:
        service = await self._ensure_service()
        await service.refresh_plugins()
        if await service.get_plugin_info(extension_name) is None:
            return None
        return await service.get_plugin_info(extension_name)

    async def discover_extensions(self) -> List[Dict[str, Any]]:
        service = await self._ensure_service()
        await service.discover_plugins(force_refresh=True)
        return self.list_extension_statuses()

    async def refresh_extensions(self) -> List[Dict[str, Any]]:
        service = await self._ensure_service()
        await service.refresh_plugins()
        return self.list_extension_statuses()

    def health_summary(self) -> Dict[str, Any]:
        service = self.service
        stats = service.get_service_stats()
        if not stats.get("initialized"):
            return {
                "runtime": {
                    "status": "not_initialized",
                    "authority": "PluginService",
                },
                "integration": self.integration.get_health_summary(),
            }
        registry_stats = stats.get("registry_stats", {})
        return {
            "runtime": {
                "status": "healthy",
                "authority": "PluginKernel",
                "discovered_count": int(
                    registry_stats.get("total_plugins", 0) or 0
                ),
                "active_executions": int(stats.get("active_executions", 0) or 0),
            },
            "integration": self.integration.get_health_summary(),
        }


_core_manager: ExtensionCoreManager | None = None


def get_extension_core_manager() -> ExtensionCoreManager:
    global _core_manager
    if _core_manager is None:
        _core_manager = ExtensionCoreManager(
            extensions_dir="src/ai_karen_engine/extensions/plugins"
        )
    return _core_manager


PluginManager = ExtensionCoreManager
