"""Echo test extension."""

from __future__ import annotations

from typing import Any, Dict

from ai_karen_engine.extensions.platform.core.host.base import ExtensionBase
from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest, ExtensionContext


class EchoExtension(ExtensionBase):
    async def initialize(self) -> None:
        self._is_initialized = True

    async def shutdown(self) -> None:
        self._is_shutdown = True

    async def execute_hook(self, hook_point: Any, context: Any) -> Dict[str, Any]:
        return {"echo": "hook"}

    async def execute(self, payload: Dict[str, Any], context: Any) -> Dict[str, Any]:
        message = payload.get("message", "")
        return {"echo": message}
