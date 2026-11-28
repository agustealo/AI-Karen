"""Standalone Content Intelligence extension entrypoint."""
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
    """Host-authorized, stateless text analysis with no external side effects."""

    def __init__(self, manifest: Any, context: ExtensionContext) -> None:
        super().__init__(manifest, context)
        self._active = False
        self._lock = asyncio.Lock()
        self._generation = 0
        # One actual worker per loaded instance. Cancellation of a caller
        # must not release this slot while its thread is still computing.
        self._worker: asyncio.Task[dict[str, Any]] | None = None

    async def initialize(self) -> None:
        async with self._lock:
            if self._worker is not None and not self._worker.done():
                raise RuntimeError("content_intelligence_worker_draining")
            if not self._active:
                self._generation += 1
                self._active = True

    async def shutdown(self) -> None:
        async with self._lock:
            self._active = False
            self._generation += 1
            worker = self._worker
            if worker is not None:
                # Drain the real work before the kernel can retire this instance.
                # Shielding does not stop a thread; it preserves the worker slot.
                try:
                    await asyncio.shield(worker)
                except Exception:
                    # Never publish payload-derived exception text on retirement.
                    pass

    def _worker_finished(self, worker: asyncio.Task[dict[str, Any]]) -> None:
        # Runs on the owning event loop, including after caller cancellation.
        if self._worker is worker:
            self._worker = None
        if not worker.cancelled():
            worker.exception()

    def get_status(self) -> dict[str, Any]:
        return {
            "status": "healthy" if self._active else "unavailable",
            "version": self.manifest.version,
            "initialized": self._active,
            "persistent_index": False,
            "llamaindex_enabled": False,
        }

    async def execute_hook(
        self, hook_point: HookPoint, context: HookContext
    ) -> dict[str, Any]:
        raise ValueError("content_intelligence_hook_not_supported")

    async def run(
        self, params: dict[str, Any], execution_context: ExtensionExecutionContext
    ) -> dict[str, Any]:
        if not self._active:
            raise RuntimeError("content_intelligence_disabled")
        if not isinstance(execution_context, ExtensionExecutionContext):
            raise PermissionError("content_verified_execution_context_required")
        try:
            tenant_id = str(uuid.UUID(str(execution_context.tenant_id)))
            user_id = str(uuid.UUID(str(execution_context.user_id)))
        except (ValueError, TypeError, AttributeError):
            raise PermissionError("content_explicit_tenant_and_user_required") from None
        # The caller supplies text it is authorized to disclose to this plugin.
        # Never accept user-supplied file paths, source IDs or metadata as ACL grants.
        async with self._lock:
            if not self._active:
                raise RuntimeError("content_intelligence_disabled")
            if self._worker is not None and not self._worker.done():
                # Do not queue private document payloads behind a cancelled call.
                raise RuntimeError("content_intelligence_busy")
            generation = self._generation
            worker = asyncio.create_task(asyncio.to_thread(execute, params))
            self._worker = worker
            worker.add_done_callback(self._worker_finished)
        # Caller cancellation propagates without cancelling the tracked worker.
        result = await asyncio.shield(worker)
        if not self._active or generation != self._generation:
            raise RuntimeError("content_intelligence_disabled")
        logger.info("content_intelligence_executed", extra={
            "tenant_id": tenant_id,
            "user_id": user_id,
            "correlation_id": execution_context.correlation_id,
            "operation": result["operation"],
            "status": "completed",
        })
        return result
