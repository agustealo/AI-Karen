"""Compatibility host manager backed by the canonical plugin service.

This module no longer imports plugin code or stores live plugin instances. The
platform host surface is retained only as a compatibility facade while runtime
state, enable/disable operations and refreshes are owned by ``PluginService`` / 
``PluginKernel``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ai_karen_engine.services.plugin_service import get_plugin_service


class ExtensionManager:
    """Thin compatibility facade over the canonical plugin runtime."""

    def __init__(
        self,
        extension_root: Path | str = "src/ai_karen_engine/extensions/plugins",
        plugin_router: Any = None,
        db_session: Any = None,
        app_instance: Any = None,
        use_new_architecture: bool = True,
        **_: Any,
    ) -> None:
        self.extension_root = Path(extension_root)
        self.plugin_router = plugin_router
        self.db_session = db_session
        self.app_instance = app_instance
        self.use_new_architecture = use_new_architecture

    async def _service(self):
        service = get_plugin_service()
        if not service.initialized:
            await service.initialize(auto_discover=True)
        return service

    def get_extension_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Return canonical catalog/runtime projection if already initialized."""
        service = get_plugin_service()
        return service.get_plugin(name)

    async def discover_extensions(self, force_refresh: bool = False) -> Dict[str, Any]:
        service = await self._service()
        return await service.discover_plugins(force_refresh=force_refresh)

    async def load_extension(self, extension_name: str) -> Optional[Dict[str, Any]]:
        """Compatibility name: enable a plugin without importing it eagerly."""
        service = await self._service()
        if await service.get_plugin_info(extension_name) is None:
            return None
        if not await service.enable_plugin(extension_name):
            return None
        return await service.get_plugin_info(extension_name)

    async def unload_extension(self, extension_name: str) -> bool:
        """Compatibility name: disable canonical execution for a plugin."""
        service = await self._service()
        return await service.disable_plugin(extension_name)
