"""Canonical facade for the unified extension core."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List

from ai_karen_engine.extensions.platform.core.host.manager import ExtensionManager
from ai_karen_engine.extensions.platform.core.host.router import get_plugin_router
from ai_karen_engine.extensions.platform.core.integration.manager import (
    get_plugin_manager,
)
from ai_karen_engine.extensions.platform.core.integration.orchestrator import (
    get_plugin_orchestrator,
)
from ai_karen_engine.extensions.platform.core.registry.plugin_registry import (
    get_registry,
)

logger = logging.getLogger(__name__)


@dataclass
class ExtensionCoreManager:
    """Coordinates registry, host runtime, and app integration concerns."""

    extensions_dir: str = "src/ai_karen_engine/extensions/plugins"

    def __post_init__(self) -> None:
        self.registry = get_registry()
        self.host = ExtensionManager(extension_root=self.extensions_dir)
        self.integration = get_plugin_manager()
        self.router = get_plugin_router()
        self.orchestrator = get_plugin_orchestrator()

    async def refresh_registry(self) -> Dict[str, Any]:
        await self.registry.refresh()
        return {
            "discovered_count": len(self.registry.list_discovered()),
            "discovered": self.registry.list_discovered(),
        }

    def _extension_capabilities(self, source: Any) -> Dict[str, bool]:
        return {
            "provides_ui": bool(getattr(source, "provides_ui", False)),
            "provides_api": bool(getattr(source, "provides_api", False)),
            "provides_background_tasks": bool(
                getattr(source, "provides_background_tasks", False)
            ),
            "provides_webhooks": bool(getattr(source, "provides_webhooks", False)),
        }

    def _build_extension_status(self, extension_name: str) -> Dict[str, Any] | None:
        record = self.registry.get_extension(extension_name)
        metadata = self.registry.get_metadata(extension_name)

        if record is None and metadata is None:
            return None

        if record is not None:
            manifest = record.manifest
            metadata = self.registry.get_metadata(extension_name)
            return {
                "id": manifest.name,
                "name": manifest.name,
                "display_name": getattr(manifest, "display_name", None)
                or manifest.name,
                "description": getattr(manifest, "description", None)
                or "No description available",
                "version": manifest.version,
                "status": record.status.value,
                "loaded_at": record.loaded_at,
                "error_message": record.error_message,
                "capabilities": self._extension_capabilities(
                    getattr(manifest, "capabilities", manifest)
                ),
                "menu_contributions": list(
                    getattr(metadata, "menu_contributions", []) or []
                ),
            }

        assert metadata is not None
        return {
            "id": metadata.name,
            "name": metadata.name,
            "display_name": metadata.display_name or metadata.name,
            "description": metadata.description or "No description available",
            "version": metadata.version,
            "status": "discovered" if metadata.is_valid else "error",
            "loaded_at": None,
            "error_message": "; ".join(metadata.validation_errors)
            if metadata.validation_errors
            else None,
            "capabilities": self._extension_capabilities(metadata.capabilities),
            "menu_contributions": list(metadata.menu_contributions or []),
        }

    def list_extension_statuses(self) -> List[Dict[str, Any]]:
        extension_ids = set(self.registry.list_discovered()) | {
            record.manifest.name for record in self.registry.list_extensions()
        }
        items = [
            self._build_extension_status(extension_id)
            for extension_id in sorted(extension_ids)
        ]
        return [item for item in items if item is not None]

    def get_extension_status(self, extension_name: str) -> Dict[str, Any] | None:
        return self._build_extension_status(extension_name)

    async def reload_runtime(self) -> Dict[str, Any]:
        manifests = await self.host.discover_extensions()
        await self.router.reload()
        return {
            "discovered_count": len(manifests),
            "loaded_count": len(self.registry.list_extensions()),
        }

    async def initialize(self) -> Dict[str, Any]:
        """Initialize the extension system and perform discovery."""
        try:
            # Initialize the registry first. This also performs initial discovery.
            await self.registry.initialize()

            # Initialize integration components
            await self.integration.initialize()

            logger.info(
                f"Extension system initialized. Discovered {len(self.registry.list_discovered())} extensions."
            )
            return self.health_summary()
        except Exception as e:
            logger.error(f"Failed to initialize extension system: {e}")
            return {"error": str(e)}

    async def load_extension(self, extension_name: str):
        return await self.host.load_extension(extension_name)

    async def unload_extension(self, extension_name: str) -> bool:
        return await self.host.unload_extension(extension_name)

    async def reload_extension(self, extension_name: str):
        if self.registry.get_extension(extension_name) is not None:
            await self.unload_extension(extension_name)
        return await self.load_extension(extension_name)

    async def discover_extensions(self) -> List[Dict[str, Any]]:
        await self.refresh_registry()
        return self.list_extension_statuses()

    async def refresh_extensions(self) -> List[Dict[str, Any]]:
        """Refresh the extension registry and return updated statuses."""
        await self.registry.refresh()
        # Also trigger host discovery if needed
        await self.host.discover_extensions()
        return self.list_extension_statuses()

    def health_summary(self) -> Dict[str, Any]:
        integration_health = self.integration.get_health_summary()
        return {
            "registry": {
                "discovered_count": len(self.registry.list_discovered()),
                "loaded_count": len(self.registry.list_extensions()),
            },
            "integration": integration_health,
        }


_core_manager: ExtensionCoreManager | None = None


def get_extension_core_manager() -> ExtensionCoreManager:
    global _core_manager
    if _core_manager is None:
        _core_manager = ExtensionCoreManager(
            extensions_dir="src/ai_karen_engine/extensions/plugins"
        )
    return _core_manager


# Backward-compatible alias for older integration surfaces that still import
# PluginManager from the unified manager facade.
PluginManager = ExtensionCoreManager
