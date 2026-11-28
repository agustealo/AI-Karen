"""Admission-only File Upload extension; the authenticated host owns discovery.

No plugin handler may write bytes, grant a destination or publish a receipt.
"""
from __future__ import annotations

from typing import Any

from ai_karen_engine.extensions.contracts import ExtensionExecutionContext
from ai_karen_engine.extensions.platform.core.host.base import (
    ExtensionBase, ExtensionContext, HookContext, HookPoint,
)


class MainExtension(ExtensionBase):
    def __init__(self, manifest: Any, context: ExtensionContext) -> None:
        super().__init__(manifest, context)
        self._active = False

    async def initialize(self) -> None:
        self._active = True

    async def shutdown(self) -> None:
        self._active = False

    def get_status(self) -> dict[str, Any]:
        return {"status": "healthy" if self._active else "unavailable",
                "version": self.manifest.version, "initialized": self._active,
                "transfer_available": False}

    async def execute_hook(self, hook_point: HookPoint, context: HookContext) -> dict[str, Any]:
        raise PermissionError("file_upload_host_admission_required")

    async def run(
        self, params: dict[str, Any], execution_context: ExtensionExecutionContext,
    ) -> dict[str, Any]:
        raise PermissionError("file_upload_host_admission_required")
