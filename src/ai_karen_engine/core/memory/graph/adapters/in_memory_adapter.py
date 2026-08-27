from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict

from ..models import EntityNode, GraphEdge


class InMemoryGraphRepository:
    """Explicit ephemeral graph repository for tests and local development.

    This repository is never durable and must not be reported as PostgreSQL,
    Supabase, Kuzu, or any other persistent graph backend.
    """

    backend_name = "in_memory"
    durable = False

    def __init__(self) -> None:
        self._ready = False
        self._entities: dict[str, dict] = {}
        self._edges: set[tuple[str, str, str, str, str | None, str | None]] = set()

    async def initialize(self) -> None:
        self._ready = True

    async def upsert_entity(
        self,
        entity: EntityNode,
        *,
        tenant_id: str,
        user_id: str,
    ) -> None:
        payload = asdict(entity)
        payload["tenant_id"] = tenant_id
        payload["user_id"] = user_id
        self._entities[entity.entity_id] = payload

    async def create_edge(self, edge: GraphEdge) -> None:
        self._edges.add(
            (
                edge.from_id,
                edge.to_id,
                edge.relationship,
                edge.tenant_id,
                edge.user_id,
                edge.conversation_id,
            )
        )

    async def find_related_events(
        self,
        tenant_id: str,
        user_id: str,
        event_id: str,
        max_depth: int = 2,
        limit: int = 20,
    ) -> list[dict]:
        if max_depth <= 0 or limit <= 0:
            return []

        adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for source, target, relation, edge_tenant, edge_user, _conversation in self._edges:
            if edge_tenant != tenant_id or (edge_user and edge_user != user_id):
                continue
            adjacency[source].append((target, relation))
            adjacency[target].append((source, relation))

        visited = {event_id}
        queue = deque([(event_id, 0)])
        results: list[dict] = []

        while queue and len(results) < limit:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbor, relation in adjacency.get(current, []):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                next_depth = depth + 1
                queue.append((neighbor, next_depth))
                results.append(
                    {
                        "event_id": neighbor,
                        "relationship": relation,
                        "depth": next_depth,
                        "source": "in_memory_graph",
                    }
                )
                if len(results) >= limit:
                    break

        return results

    async def find_entity_context(
        self,
        tenant_id: str,
        user_id: str,
        entity_text: str,
        max_depth: int = 2,
        limit: int = 20,
    ) -> list[dict]:
        normalized = entity_text.strip().casefold()
        matching_ids = [
            entity_id
            for entity_id, payload in self._entities.items()
            if payload.get("tenant_id") == tenant_id
            and payload.get("user_id") == user_id
            and str(payload.get("normalized") or payload.get("text") or "").casefold()
            == normalized
        ]

        results: list[dict] = []
        for entity_id in matching_ids:
            related = await self.find_related_events(
                tenant_id=tenant_id,
                user_id=user_id,
                event_id=entity_id,
                max_depth=max_depth,
                limit=max(0, limit - len(results)),
            )
            results.extend(related)
            if len(results) >= limit:
                break
        return results[:limit]

    async def close(self) -> None:
        self._ready = False
        self._entities.clear()
        self._edges.clear()


__all__ = ["InMemoryGraphRepository"]
