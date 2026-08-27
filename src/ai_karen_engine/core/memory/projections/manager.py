"""Projection coordinator for governed AI KAREN memory events.

Core coordinates projection workers but does not construct vendor/platform
implementations. Runtime/platform composition injects the configured workers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.runtime.resilience import get_safe_stage_runner

from .base import ProjectionWorker

logger = get_logger(__name__)


class ProjectionManager:
    """Fan out committed memory events to explicitly injected projections."""

    def __init__(self, workers: Mapping[str, ProjectionWorker]) -> None:
        normalized = {
            str(name).strip(): worker
            for name, worker in workers.items()
            if str(name).strip() and worker is not None
        }
        if not normalized:
            raise ValueError("ProjectionManager requires at least one projection worker")
        self.workers = normalized
        self.safe_runner = get_safe_stage_runner()

    async def project_event(
        self,
        event_data: dict[str, Any],
        assertion_data: dict[str, Any] | None = None,
    ) -> dict[str, bool]:
        event_id = str(event_data.get("event_id") or "")
        tenant_id = str(event_data.get("tenant_id") or "")
        user_id = str(event_data.get("user_id") or "")

        tasks = []
        names: list[str] = []
        for store_name, worker in self.workers.items():
            flag_name = (
                "graph_relationships_enabled"
                if store_name == "memory_graph"
                else "memory_learning_enabled"
            )
            names.append(store_name)
            tasks.append(
                self.safe_runner.run_stage(
                    stage_name=f"{store_name}_projection",
                    flag_name=flag_name,
                    func=worker.project,
                    event_data=event_data,
                    assertion_data=assertion_data,
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
            )

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        results: dict[str, bool] = {}
        for store_name, value in zip(names, raw_results):
            if isinstance(value, Exception):
                logger.error(
                    "memory.projection.failed",
                    extra={
                        "event_id": event_id,
                        "target_store": store_name,
                        "error_type": type(value).__name__,
                    },
                )
                results[store_name] = False
                continue

            results[store_name] = bool(value)
            if not value:
                logger.warning(
                    "memory.projection.blocked_or_failed",
                    extra={"event_id": event_id, "target_store": store_name},
                )
        return results


__all__ = ["ProjectionManager"]
