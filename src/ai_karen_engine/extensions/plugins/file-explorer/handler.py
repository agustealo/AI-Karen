"""Shared File Explorer extension, without filesystem or storage ownership."""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from ai_karen_engine.extensions.contracts import ExtensionExecutionContext
from ai_karen_engine.extensions.platform.core.host.base import (
    ExtensionBase,
    ExtensionContext,
    HookContext,
    HookPoint,
)

from .engine import execute

logger = logging.getLogger(__name__)


class MainExtension(ExtensionBase):
    def __init__(self, manifest: Any, context: ExtensionContext) -> None:
        super().__init__(manifest, context)
        self._active = False
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        async with self._lock:
            self._active = True

    async def shutdown(self) -> None:
        async with self._lock:
            self._active = False

    def get_status(self) -> dict[str, Any]:
        return {
            "status": "healthy" if self._active else "unavailable",
            "version": self.manifest.version,
            "initialized": self._active,
            "live_file_integration": False,
        }

    async def execute_hook(self, hook_point: HookPoint, context: HookContext) -> dict[str, Any]:
        raise ValueError("file_explorer_hook_not_supported")

    async def run(
        self, params: dict[str, Any], execution_context: ExtensionExecutionContext
    ) -> dict[str, Any]:
        async with self._lock:
            if not self._active:
                raise RuntimeError("file_explorer_disabled")
            if not isinstance(execution_context, ExtensionExecutionContext):
                raise PermissionError("file_explorer_host_context_required")
            try:
                tenant_id = str(uuid.UUID(str(execution_context.tenant_id)))
                user_id = str(uuid.UUID(str(execution_context.user_id)))
            except (ValueError, TypeError, AttributeError):
                raise PermissionError("file_explorer_explicit_scope_required") from None
            scope = execution_context.resource_scope
            if (
                not isinstance(scope, dict)
                or scope.get("file_explorer_grant") != "host_verified"
                or not isinstance(execution_context.policy_decision_id, str)
                or not execution_context.policy_decision_id
                or "file-explorer" not in execution_context.allowed_capabilities
            ):
                raise PermissionError("file_explorer_authorization_required")
            # These entries are a host-owned authorized snapshot, not request payload.
            # The consumer must revalidate source ACL/revision before opening bytes.
            inventory = scope.get("file_explorer_entries")
            if inventory is None:
                raise PermissionError("file_explorer_inventory_required")
            result = await asyncio.to_thread(execute, params, inventory)
            logger.info("file_explorer_executed", extra={
                "tenant_id": tenant_id, "user_id": user_id,
                "correlation_id": execution_context.correlation_id,
                "operation": result["operation"], "status": "completed",
            })
            return result
