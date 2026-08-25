"""
Projection Manager for AI Karen Memory System.

Orchestrates multiple projection workers to fan out memory events.
"""

import asyncio
import logging
from typing import Any

from ...runtime.resilience import get_safe_stage_runner
from .base import ProjectionWorker
from .duckdb_worker import DuckDBWorker
from .leangraph_worker import LeanGraphWorker
from .redis_worker import RedisWorker

logger = logging.getLogger(__name__)

class ProjectionManager:
    """Manages the fan-out of memory projections."""

    def __init__(self):
        self.workers: dict[str, ProjectionWorker] = {
            "redis": RedisWorker(),
            "leangraph": LeanGraphWorker(),
            "duckdb": DuckDBWorker()
        }
        self.safe_runner = get_safe_stage_runner()

    async def project_event(self, event_data: dict[str, Any], assertion_data: dict[str, Any] | None = None):
        """
        Fan out the event to all registered workers.
        Uses SafeStageRunner for each projection to ensure isolation and resilience.
        """
        event_id = str(event_data.get("event_id"))
        tenant_id = str(event_data.get("tenant_id"))
        user_id = str(event_data.get("user_id"))

        tasks = []
        for store_name, worker in self.workers.items():
            flag_name = f"{store_name}_enabled"
            if store_name == "leangraph":
                flag_name = "graph_relationships_enabled"

            tasks.append(
                self.safe_runner.run_stage(
                    stage_name=f"{store_name}_projection",
                    flag_name=flag_name,
                    func=worker.project,
                    event_data=event_data,
                    assertion_data=assertion_data,
                    tenant_id=tenant_id,
                    user_id=user_id
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for idx, (store_name, _) in enumerate(self.workers.items()):
            res = results[idx]
            if isinstance(res, Exception):
                logger.error(f"Projection to {store_name} failed with exception: {res}")
            elif res is False:
                logger.warning(f"Projection to {store_name} returned False (failed/blocked).")
            else:
                logger.debug(f"Projection to {store_name} successful for event {event_id}")

projection_manager = ProjectionManager()

def get_projection_manager() -> ProjectionManager:
    return projection_manager