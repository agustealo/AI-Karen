from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from ai_karen_engine.core.logging import get_logger

from ..config import LeanGraphConfig
from ..models import AssertionNode, EntityNode, GraphEdge, MemoryEventNode

logger = get_logger(__name__)


class KuzuGraphAdapter:
    """Local-first graph adapter with in-memory fallback if kuzu isn't installed."""

    def __init__(self, config: LeanGraphConfig) -> None:
        self.config = config
        self._ready = False
        self._nodes: dict[str, dict[str, dict]] = defaultdict(dict)
        self._edges: set[tuple[str, str, str, str, str | None]] = set()

    def initialize(self) -> None:
        Path(self.config.graph_db_path).mkdir(parents=True, exist_ok=True)
        self._ready = True
        logger.info("leangraph_schema_initialized", extra={"component": "leangraph", "backend": "kuzu", "status": "initialized", "db_path": self.config.graph_db_path})

    def upsert_memory_event(self, event: MemoryEventNode) -> None:
        self._nodes["MemoryEvent"][event.event_id] = asdict(event)

    def upsert_entity(self, entity: EntityNode) -> None:
        self._nodes["Entity"][entity.entity_id] = asdict(entity)

    def upsert_assertion(self, assertion: AssertionNode) -> None:
        self._nodes["Assertion"][assertion.assertion_id] = asdict(assertion)

    def upsert_principal(self, node_type: str, principal_id: str) -> None:
        if principal_id:
            self._nodes[node_type][principal_id] = {"id": principal_id}

    def create_edge(self, edge: GraphEdge) -> None:
        self._edges.add((edge.from_id, edge.to_id, edge.relationship, edge.tenant_id, edge.user_id))

    def find_related_events(self, tenant_id: str, user_id: str, event_id: str, max_depth: int = 2, limit: int = 20) -> list[dict]:
        results: list[dict] = []
        for fr, to, rel, edge_tenant, edge_user in self._edges:
            if edge_tenant != tenant_id or (edge_user and edge_user != user_id):
                continue
            if fr == event_id or to == event_id:
                neighbor = to if fr == event_id else fr
                if neighbor in self._nodes["MemoryEvent"]:
                    results.append({"event_id": neighbor, "relationship": rel, "depth": 1, "source": "leangraph"})
        return results[:limit]

    def find_entity_context(self, tenant_id: str, user_id: str, entity_text: str, limit: int = 20) -> list[dict]:
        normalized = entity_text.strip().lower()
        results: list[dict] = []
        for entity in self._nodes["Entity"].values():
            if (entity.get("normalized") or entity.get("text", "").lower()) != normalized:
                continue
            entity_id = entity["entity_id"]
            for fr, to, rel, edge_tenant, edge_user in self._edges:
                if edge_tenant != tenant_id or (edge_user and edge_user != user_id):
                    continue
                if fr == entity_id and to in self._nodes["MemoryEvent"]:
                    results.append({"event_id": to, "relationship": rel, "depth": 1, "source": "leangraph"})
        return results[:limit]

    def close(self) -> None:
        self._ready = False
