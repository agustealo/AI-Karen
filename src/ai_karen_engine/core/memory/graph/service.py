from __future__ import annotations

import time
import uuid

from ai_karen_engine.core.logging import get_logger

from .adapters.base import GraphRepository
from .config import LeanGraphConfig
from .models import AssertionNode, EntityNode, GraphEdge, MemoryEventNode

logger = get_logger(__name__)


class LeanGraphService:
    """Memory-domain graph projection/query service.

    The historical class name is retained for compatibility. Storage is selected
    through the canonical GraphRepository contract and defaults to PostgreSQL.
    """

    def __init__(
        self,
        config: LeanGraphConfig | None = None,
        repository: GraphRepository | None = None,
    ) -> None:
        self.config = config or LeanGraphConfig.from_env()
        self.config.validate()
        self.adapter = repository or self._build_repository(self.config)
        self._initialized = False
        self._circuit_open_until = 0.0
        self._consecutive_failures = 0
        self._failure_threshold = 3
        self._cooldown_seconds = 30

    @staticmethod
    def _build_repository(config: LeanGraphConfig) -> GraphRepository:
        backend = config.graph_backend.strip().lower()
        if backend == "in_memory":
            from .adapters.in_memory_adapter import InMemoryGraphRepository

            return InMemoryGraphRepository()
        if backend == "postgres":
            from ai_karen_engine.platform.memory.postgres.graph_repository import (
                PostgresGraphRepository,
            )

            return PostgresGraphRepository()
        raise ValueError(f"unsupported memory graph backend: {config.graph_backend!r}")

    async def initialize(self) -> None:
        if self._initialized:
            return
        if not self.config.graph_relationships_enabled:
            logger.info(
                "memory_graph_disabled",
                extra={"component": "memory_graph", "status": "disabled"},
            )
            self._initialized = True
            return
        await self.adapter.initialize()
        self._initialized = True
        logger.info(
            "memory_graph_initialized",
            extra={
                "component": "memory_graph",
                "backend": getattr(self.adapter, "backend_name", self.config.graph_backend),
                "durable": getattr(self.adapter, "durable", None),
                "status": "initialized",
            },
        )

    async def project_memory_event(
        self,
        event_data: dict,
        assertion_data: dict | None = None,
    ) -> bool:
        await self.initialize()
        if not self.config.graph_relationships_enabled:
            return True

        now = time.time()
        if now < self._circuit_open_until:
            logger.warning(
                "memory_graph_projection_skipped_circuit_open",
                extra={
                    "component": "memory_graph",
                    "status": "degraded",
                    "retry_after_s": round(self._circuit_open_until - now, 2),
                },
            )
            return False

        started = time.time()
        event_id = str(event_data.get("event_id") or "").strip()
        tenant_id = str(event_data.get("tenant_id") or "").strip()
        user_id = str(event_data.get("user_id") or "").strip()
        conversation_id = event_data.get("conversation_id")
        if not event_id or not tenant_id or not user_id:
            logger.warning(
                "memory_graph_projection_rejected",
                extra={
                    "component": "memory_graph",
                    "status": "rejected",
                    "event_id": event_id or None,
                    "tenant_id": tenant_id or None,
                    "user_id": user_id or None,
                    "reason": "missing_scope_or_event_id",
                },
            )
            return False

        try:
            # Event/assertion records are canonical PostgreSQL ledger records. The
            # graph references them; it does not duplicate them as graph-owned rows.
            event_node = MemoryEventNode(
                event_id=event_id,
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=str(conversation_id) if conversation_id else None,
                memory_type=event_data.get("memory_type"),
                created_at=event_data.get("created_at"),
                importance=event_data.get("importance"),
                source=event_data.get("source"),
            )
            del event_node

            edge_count = 0
            entities = (event_data.get("payload") or {}).get("entities", [
            ])[: self.config.graph_max_entities_per_event]
            if self.config.graph_enable_entity_mentions:
                for ent in entities:
                    if edge_count >= self.config.graph_max_edges_per_event:
                        break
                    text = str(ent.get("text") or "").strip()
                    if not text:
                        continue
                    normalized = text.casefold()
                    entity_id = self._entity_id(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        normalized=normalized,
                        entity_type=ent.get("type"),
                        supplied_id=ent.get("entity_id"),
                    )
                    await self.adapter.upsert_entity(
                        EntityNode(
                            entity_id=entity_id,
                            text=text,
                            type=ent.get("type"),
                            normalized=normalized,
                        ),
                        tenant_id=tenant_id,
                        user_id=user_id,
                    )
                    await self.adapter.create_edge(
                        GraphEdge(
                            entity_id,
                            event_id,
                            "MENTIONS",
                            tenant_id,
                            user_id,
                            str(conversation_id) if conversation_id else None,
                            metadata={"source_event_id": event_id},
                        )
                    )
                    edge_count += 1

            supersedes = event_data.get("supersedes")
            if (
                supersedes
                and self.config.graph_enable_supersedes_edges
                and edge_count < self.config.graph_max_edges_per_event
            ):
                await self.adapter.create_edge(
                    GraphEdge(
                        event_id,
                        str(supersedes),
                        "SUPERSEDES",
                        tenant_id,
                        user_id,
                        metadata={"source_event_id": event_id},
                    )
                )
                edge_count += 1

            if assertion_data and edge_count < self.config.graph_max_edges_per_event:
                assertion_id = str(
                    assertion_data.get("assertion_id") or f"assert:{event_id}"
                )
                assertion_node = AssertionNode(
                    assertion_id=assertion_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    text=str(assertion_data.get("text") or ""),
                    confidence=assertion_data.get("confidence"),
                    polarity=assertion_data.get("polarity"),
                    created_at=assertion_data.get("created_at"),
                )
                del assertion_node
                await self.adapter.create_edge(
                    GraphEdge(
                        event_id,
                        assertion_id,
                        "ASSERTS",
                        tenant_id,
                        user_id,
                        metadata={"source_event_id": event_id},
                    )
                )
                edge_count += 1

                if self.config.graph_enable_contradiction_edges:
                    for contradiction_id in assertion_data.get("contradicts", []):
                        if edge_count >= self.config.graph_max_edges_per_event:
                            break
                        await self.adapter.create_edge(
                            GraphEdge(
                                assertion_id,
                                str(contradiction_id),
                                "CONTRADICTS",
                                tenant_id,
                                user_id,
                                metadata={"source_event_id": event_id},
                            )
                        )
                        edge_count += 1

                if self.config.graph_enable_reinforcement_edges:
                    for reinforcement_id in assertion_data.get("reinforces", []):
                        if edge_count >= self.config.graph_max_edges_per_event:
                            break
                        await self.adapter.create_edge(
                            GraphEdge(
                                assertion_id,
                                str(reinforcement_id),
                                "REINFORCES",
                                tenant_id,
                                user_id,
                                metadata={"source_event_id": event_id},
                            )
                        )
                        edge_count += 1

            logger.info(
                "memory_graph_projection_completed",
                extra={
                    "component": "memory_graph",
                    "backend": getattr(self.adapter, "backend_name", self.config.graph_backend),
                    "status": "completed",
                    "event_id": event_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "edge_count": edge_count,
                    "latency_ms": (time.time() - started) * 1000,
                },
            )
            self._consecutive_failures = 0
            return True
        except Exception as exc:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._circuit_open_until = time.time() + self._cooldown_seconds
            logger.exception(
                "memory_graph_projection_failed",
                extra={
                    "component": "memory_graph",
                    "backend": getattr(self.adapter, "backend_name", self.config.graph_backend),
                    "status": "failed",
                    "event_id": event_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "error_type": type(exc).__name__,
                },
            )
            return False

    async def get_related_context(
        self,
        tenant_id: str,
        user_id: str,
        event_id: str,
        max_depth: int = 2,
        limit: int = 20,
    ) -> list[dict]:
        await self.initialize()
        return await self.adapter.find_related_events(
            tenant_id=tenant_id,
            user_id=user_id,
            event_id=event_id,
            max_depth=max_depth,
            limit=limit,
        )

    async def get_entity_context(
        self,
        tenant_id: str,
        user_id: str,
        entity_text: str,
        max_depth: int = 2,
        limit: int = 20,
    ) -> list[dict]:
        await self.initialize()
        return await self.adapter.find_entity_context(
            tenant_id=tenant_id,
            user_id=user_id,
            entity_text=entity_text,
            max_depth=max_depth,
            limit=limit,
        )

    async def close(self) -> None:
        await self.adapter.close()
        self._initialized = False

    @staticmethod
    def _entity_id(
        *,
        tenant_id: str,
        user_id: str,
        normalized: str,
        entity_type: str | None,
        supplied_id: object | None,
    ) -> str:
        if supplied_id:
            try:
                return str(uuid.UUID(str(supplied_id)))
            except ValueError:
                external_key = str(supplied_id)
        else:
            external_key = normalized
        material = (
            f"ai-karen-memory-entity:{tenant_id}:{user_id}:"
            f"{entity_type or 'unknown'}:{external_key}:{normalized}"
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, material))


_SERVICE: LeanGraphService | None = None


def get_leangraph_service() -> LeanGraphService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = LeanGraphService()
    return _SERVICE
