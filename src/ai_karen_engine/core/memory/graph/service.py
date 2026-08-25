from __future__ import annotations

import time

from ai_karen_engine.core.logging import get_logger

from .adapters.kuzu_adapter import KuzuGraphAdapter
from .config import LeanGraphConfig
from .models import AssertionNode, EntityNode, GraphEdge, MemoryEventNode

logger = get_logger(__name__)


class LeanGraphService:
    def __init__(self, config: LeanGraphConfig | None = None) -> None:
        self.config = config or LeanGraphConfig.from_env()
        self.adapter = KuzuGraphAdapter(self.config)
        self._initialized = False
        self._circuit_open_until = 0.0
        self._consecutive_failures = 0
        self._failure_threshold = 3
        self._cooldown_seconds = 30

    def initialize(self) -> None:
        if self._initialized:
            return
        if not self.config.graph_relationships_enabled:
            logger.info("leangraph_disabled", extra={"component": "leangraph", "status": "disabled"})
            self._initialized = True
            return
        self.adapter.initialize()
        self._initialized = True

    async def project_memory_event(self, event_data: dict, assertion_data: dict | None = None) -> bool:
        self.initialize()
        if not self.config.graph_relationships_enabled:
            return True
        now = time.time()
        if now < self._circuit_open_until:
            logger.warning("leangraph_projection_skipped_circuit_open", extra={"component": "leangraph", "status": "degraded", "retry_after_s": round(self._circuit_open_until - now, 2)})
            return False
        started = time.time()
        event_id = str(event_data.get("event_id") or "")
        tenant_id = str(event_data.get("tenant_id") or "")
        user_id = str(event_data.get("user_id") or "")
        conversation_id = event_data.get("conversation_id")
        try:
            self.adapter.upsert_principal("Tenant", tenant_id)
            self.adapter.upsert_principal("User", user_id)
            if conversation_id:
                self.adapter.upsert_principal("Conversation", str(conversation_id))

            event_node = MemoryEventNode(event_id=event_id, tenant_id=tenant_id, user_id=user_id, conversation_id=str(conversation_id) if conversation_id else None, memory_type=event_data.get("memory_type"), created_at=event_data.get("created_at"), importance=event_data.get("importance"), source=event_data.get("source"))
            self.adapter.upsert_memory_event(event_node)
            self.adapter.create_edge(GraphEdge(event_id, tenant_id, "BELONGS_TO_TENANT", tenant_id, user_id))
            self.adapter.create_edge(GraphEdge(event_id, user_id, "BELONGS_TO_USER", tenant_id, user_id))
            if conversation_id:
                self.adapter.create_edge(GraphEdge(event_id, str(conversation_id), "OCCURRED_IN_CONVERSATION", tenant_id, user_id, str(conversation_id)))

            entities = (event_data.get("payload") or {}).get("entities", [])[: self.config.graph_max_entities_per_event]
            for ent in entities:
                text = str(ent.get("text") or "").strip()
                if not text:
                    continue
                entity_id = str(ent.get("entity_id") or f"{tenant_id}:{text.lower()}")
                self.adapter.upsert_entity(EntityNode(entity_id=entity_id, text=text, type=ent.get("type"), normalized=text.lower()))
                self.adapter.create_edge(GraphEdge(entity_id, event_id, "MENTIONS", tenant_id, user_id, str(conversation_id) if conversation_id else None))

            supersedes = event_data.get("supersedes")
            if supersedes and self.config.graph_enable_supersedes_edges:
                self.adapter.create_edge(GraphEdge(event_id, str(supersedes), "SUPERSEDES", tenant_id, user_id))

            if assertion_data:
                assertion_id = str(assertion_data.get("assertion_id") or f"assert:{event_id}")
                self.adapter.upsert_assertion(AssertionNode(assertion_id=assertion_id, user_id=user_id, tenant_id=tenant_id, text=str(assertion_data.get("text") or ""), confidence=assertion_data.get("confidence"), polarity=assertion_data.get("polarity"), created_at=assertion_data.get("created_at")))
                self.adapter.create_edge(GraphEdge(event_id, assertion_id, "ASSERTS", tenant_id, user_id))
                for cid in assertion_data.get("contradicts", []) if self.config.graph_enable_contradiction_edges else []:
                    self.adapter.create_edge(GraphEdge(assertion_id, str(cid), "CONTRADICTS", tenant_id, user_id))
                for rid in assertion_data.get("reinforces", []) if self.config.graph_enable_reinforcement_edges else []:
                    self.adapter.create_edge(GraphEdge(assertion_id, str(rid), "REINFORCES", tenant_id, user_id))

            logger.info("leangraph_projection_completed", extra={"component": "leangraph", "status": "completed", "event_id": event_id, "tenant_id": tenant_id, "user_id": user_id, "latency_ms": (time.time()-started)*1000})
            self._consecutive_failures = 0
            return True
        except Exception as exc:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._circuit_open_until = time.time() + self._cooldown_seconds
            logger.exception("leangraph_projection_failed", extra={"component": "leangraph", "status": "failed", "event_id": event_id, "tenant_id": tenant_id, "user_id": user_id, "error_type": type(exc).__name__})
            return False

    async def get_related_context(self, tenant_id: str, user_id: str, event_id: str, max_depth: int = 2, limit: int = 20) -> list[dict]:
        self.initialize()
        return self.adapter.find_related_events(tenant_id=tenant_id, user_id=user_id, event_id=event_id, max_depth=max_depth, limit=limit)

    async def get_entity_context(self, tenant_id: str, user_id: str, entity_text: str, limit: int = 20) -> list[dict]:
        self.initialize()
        return self.adapter.find_entity_context(tenant_id=tenant_id, user_id=user_id, entity_text=entity_text, limit=limit)


_SERVICE: LeanGraphService | None = None


def get_leangraph_service() -> LeanGraphService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = LeanGraphService()
    return _SERVICE
