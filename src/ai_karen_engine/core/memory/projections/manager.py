"""Projection manager for governed AI KAREN memory events."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ...runtime.resilience import get_safe_stage_runner
from .base import ProjectionWorker
from .memory_graph_worker import MemoryGraphWorker
from .redis_worker import RedisWorker

logger = logging.getLogger(__name__)


class ProjectionManager:
    """Fan out committed memory events to active derived projections only."""

    def __init__(self) -> None:
        self.workers: dict[str, ProjectionWorker] = {
            "redis": RedisWorker(),
            "memory_graph": MemoryGraphWorker(),
        }
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
                    "memory_projection_failed",
                    extra={
                        "event_id": event_id,
                        "target_store": store_name,
                        "error_type": type(value).__name__,
                    },
                )
                results[store_name] = False
            else:
                results[store_name] = bool(value)
                if not value:
                    logger.warning(
                        "memory_projection_blocked_or_failed",
                        extra={"event_id": event_id, "target_store": store_name},
                    )
        return results


projection_manager = ProjectionManager()


def get_projection_manager() -> ProjectionManager:
    return projection_manager
