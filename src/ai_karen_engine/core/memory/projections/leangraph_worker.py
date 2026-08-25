"""
LeanGraph Projection Worker for AI Karen Memory System.

Projects relationship-heavy memory metadata into LeanGraph.
Focuses on contradictions, reinforcements, and multi-hop links.
"""

from typing import Any

from ai_karen_engine.core.memory.graph.service import get_leangraph_service

from .base import ProjectionWorker

logger = logging.getLogger(__name__)

class LeanGraphWorker(ProjectionWorker):
    """Worker responsible for relationship projections in LeanGraph."""

    def __init__(self):
        super().__init__("leangraph")
        # Keep worker thin: translation only. Backend selection and schema ownership
        # live in core.memory.graph.service.
        self._graph_service = get_leangraph_service()

    async def project(self, event_data: dict[str, Any], assertion_data: dict[str, Any] | None = None) -> bool:
        """
        Project relationship data into graph.
        Focuses on building links between entities and detecting contradictions.
        """
        try:
            return await self._graph_service.project_memory_event(
                event_data=event_data,
                assertion_data=assertion_data,
            )

        except Exception as e:
            logger.error(f"Error projecting to LeanGraph for event {event_data.get('event_id')}: {e}")
            return False
