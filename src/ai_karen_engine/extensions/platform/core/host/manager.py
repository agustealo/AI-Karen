"""Compatibility host manager backed by the canonical PluginService.

The historical host manager used to import plugin modules directly and mutate a
second loaded-instance registry. That execution authority is retired. This
surface now exposes catalog refresh plus enable/disable state changes only;
plugin code is imported lazily by PluginKernel after authorization succeeds.

PluginService access is lazy so importing the platform host package while
PluginKernel is initializing cannot recurse back into PluginKernel.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from ai_karen_engine.services.plugin_service import PluginService


def get_plugin_service() -> "PluginService":
    from ai_karen_engine.services.plugin_service import get_plugin_service as _get

    return _get()


async def initialize_plugin_service(**kwargs: Any) -> "PluginService":
    from ai_karen_engine.services.plugin_service import (
        initialize_plugin_service as _initialize,
    )

    return await _initialize(**kwargs)


class ExtensionManager:
    """Legacy host facade with no direct loader or executor authority."""

    def __init__(
        self,
        extension_root: Path | str = "src/ai_karen_engine/extensions/plugins",
        plugin_router: Any = None,
        db_session: Any = None,
        app_instance: Any = None,
        use_new_architecture: bool = True,
        **_: Any,
    ) -> None:
        del plugin_router, db_session, app_instance, use_new_architecture
        self.extension_root = Path(extension_root)
        self._discovery_cache: Optional[Dict[str, Any]] = None

    def _service(self) -> "PluginService":
        service = get_plugin_service()
        if service.initialized:
            active_root = Path(
                service.core_plugins_path
                or service.marketplace_path
                or "src/ai_karen_engine/extensions/plugins"
            )
            if active_root.resolve() != self.extension_root.resolve():
                raise RuntimeError(
                    "ExtensionManager root does not match the initialized PluginService"
                )
        return service

    async def _ensure_service(self) -> "PluginService":
        service = self._service()
        if service.initialized:
            return service
        return await initialize_plugin_service(
            marketplace_path=self.extension_root,
            core_plugins_path=self.extension_root,
            auto_discover=True,
        )

    def get_extension_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Return canonical catalog/runtime status for a plugin."""
        return self._service().get_plugin(name)

    async def discover_extensions(
        self, force_refresh: bool = False
    ) -> Dict[str, Any]:
        service = await self._ensure_service()
        records = await service.discover_plugins(force_refresh=force_refresh)
        self._discovery_cache = {
            plugin_id: record["manifest"]
            for plugin_id, record in records.items()
            if record.get("manifest") is not None
        }
        return dict(self._discovery_cache)

    async def load_extension(self, extension_name: str) -> Optional[Dict[str, Any]]:
        """Compatibility name: enable without importing plugin code eagerly."""
        service = await self._ensure_service()
        if not await service.enable_plugin(extension_name):
            return None
        return await service.get_plugin_info(extension_name)

    async def unload_extension(self, extension_name: str) -> bool:
        """Compatibility name: disable in the canonical runtime."""
        service = await self._ensure_service()
        return await service.disable_plugin(extension_name)
