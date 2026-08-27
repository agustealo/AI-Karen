from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import EntityNode, GraphEdge


@runtime_checkable
class GraphRepository(Protocol):
    """Backend-neutral, async-safe memory graph projection/query contract."""

    async def initialize(self) -> None: ...

    async def upsert_entity(
        self,
        entity: EntityNode,
        *,
        tenant_id: str,
        user_id: str,
    ) -> None: ...

    async def create_edge(self, edge: GraphEdge) -> None: ...

    async def find_related_events(
        self,
        tenant_id: str,
        user_id: str,
        event_id: str,
        max_depth: int = 2,
        limit: int = 20,
    ) -> list[dict]: ...

    async def find_entity_context(
        self,
        tenant_id: str,
        user_id: str,
        entity_text: str,
        max_depth: int = 2,
        limit: int = 20,
    ) -> list[dict]: ...

    async def close(self) -> None: ...


# Compatibility alias while consumers migrate to the canonical repository name.
GraphAdapter = GraphRepository

__all__ = ["GraphAdapter", "GraphRepository"]
