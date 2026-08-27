"""Canonical memory-graph projection worker.

The worker is translation-only. Backend selection, durability, schema, and
traversal remain owned by ``core.memory.graph`` and its platform repository.
"""

from __future__ import annotations

import logging
from typing import Any

from ai_karen_engine.core.memory.graph.service import get_leangraph_service

from .base import ProjectionWorker

logger = logging.getLogger(__name__)


class MemoryGraphWorker(ProjectionWorker):
    """Project governed memory events into the canonical memory graph."""

    def __init__(self) -> None:
        super().__init__("memory_graph")
        self._graph_service = get_leangraph_service()

    async def project(
        self,
        event_data: dict[str, Any],
        assertion_data: dict[str, Any] | None = None,
    ) -> bool:
        try:
            return await self._graph_service.project_memory_event(
                event_data=event_data,
                assertion_data=assertion_data,
            )
        except Exception as exc:
            logger.exception(
                "memory_graph_projection_worker_failed",
                extra={
                    "event_id": event_data.get("event_id"),
                    "error_type": type(exc).__name__,
                },
            )
            return False


__all__ = ["MemoryGraphWorker"]
