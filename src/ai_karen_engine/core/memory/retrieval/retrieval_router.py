from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.memory.graph.service import get_leangraph_service
from ai_karen_engine.core.runtime.resilience import get_safe_stage_runner
from ai_karen_engine.platform.memory.redis.redis_connection_manager import get_redis_manager

from ..neuro import decide_activation_mode, emit_memory_event
from ..types import (
    MemoryEntry,
    MemoryMetadata,
    MemoryNamespace,
    MemoryQuery,
    MemoryType,
)

logger = get_logger(__name__)


class HybridRetrievalRouter:
    """Retrieve bounded non-durable-source candidates for NeuroRecall.

    This router is intentionally *not* a recall authority. It may decide which
    source adapters are worth querying for latency reasons, but it does not fuse,
    guard, rerank, deduplicate, or make final selection decisions. NeuroRecall
    owns those responsibilities.
    """

    def __init__(self) -> None:
        self.safe_runner = get_safe_stage_runner()
        self.redis = get_redis_manager()
        self.leangraph = get_leangraph_service()

    async def recall(self, query: MemoryQuery) -> list[MemoryEntry]:
        started = time.time()
        correlation_id = str(uuid.uuid4())
        tenant_id = str(query.tenant_id or "")
        user_id = str(query.user_id or "")

        if not tenant_id or not user_id:
            logger.warning("memory.source_router.degraded", extra={"reason": "missing_tenant_or_user"})
            return []

        activation = decide_activation_mode(query=query.text or "", latency_budget_ms=300)
        emit_memory_event(
            "memory.activation.completed",
            {
                "correlation_id": correlation_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "memory_activation_mode": activation.mode.value,
                "token_budget": activation.top_k,
            },
        )

        candidates: list[MemoryEntry] = []
        stores_queried: list[str] = []

        if activation.mode.value != "none":
            stores_queried.append("redis")
            hot = await self.safe_runner.run_stage(
                "memory_fast_recall",
                "memory_learning_enabled",
                self._query_redis,
                query,
                tenant_id=tenant_id,
                user_id=user_id,
            ) or []
            candidates.extend(hot)

        if activation.include_graph:
            stores_queried.append("graph")
            graph = await self.safe_runner.run_stage(
                "memory_graph_expansion",
                "memory_learning_enabled",
                self._query_graph,
                query,
                tenant_id=tenant_id,
                user_id=user_id,
            ) or []
            candidates.extend(graph)

        emit_memory_event(
            "memory.source_router.completed",
            {
                "correlation_id": correlation_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "memory_activation_mode": activation.mode.value,
                "stores_queried": stores_queried,
                "candidate_count": len(candidates),
                "latency_ms": (time.time() - started) * 1000,
            },
        )
        return candidates

    async def _query_redis(self, query: MemoryQuery) -> list[MemoryEntry]:
        session_id = getattr(query, "session_id", None)
        data = await self.redis.get_session(
            str(query.tenant_id),
            str(query.user_id),
            session_id=session_id,
        )
        if not data:
            data = await self.redis.get_short_term(str(query.tenant_id), str(query.user_id))
        if not data:
            return []

        content = str(data.get("summary") or data.get("last_message") or data)
        return [
            self._entry(
                query,
                content,
                "redis",
                MemoryType.EPISODIC,
                semantic=0.3,
                lexical=0.4,
                stable_id=self._redis_candidate_id(query),
                provenance={
                    "store": "redis",
                    "session_id": session_id,
                    "ephemeral": True,
                },
            )
        ]

    async def _query_graph(self, query: MemoryQuery) -> list[MemoryEntry]:
        if not query.text:
            return []
        try:
            results = await self.leangraph.get_entity_context(
                tenant_id=str(query.tenant_id),
                user_id=str(query.user_id),
                entity_text=query.text,
                limit=min(20, max(2, query.top_k * 2)),
            )
        except Exception as exc:
            logger.warning(
                "memory.graph_source.failed",
                extra={
                    "tenant_id": query.tenant_id,
                    "user_id": query.user_id,
                    "error_type": type(exc).__name__,
                },
            )
            return []

        entries: list[MemoryEntry] = []
        for row in results or []:
            event_id = str(row.get("event_id") or "").strip()
            if not event_id:
                continue

            payload = row.get("payload")
            content = self._content_from_graph_payload(payload)
            if not content:
                # A graph path without canonical source content is evidence for
                # expansion, not a synthetic memory. Skip rather than invent text.
                continue

            entries.append(
                self._entry(
                    query,
                    content,
                    "graph",
                    MemoryType.EPISODIC,
                    semantic=float(row.get("graph_score") or 0.55),
                    stable_id=event_id,
                    timestamp=self._coerce_datetime(row.get("created_at")),
                    confidence=float(row.get("confidence") or 0.8),
                    provenance={
                        "store": "postgres_graph",
                        "record_type": "memory_event",
                        "event_id": event_id,
                        "relationship": row.get("relationship"),
                        "depth": row.get("depth"),
                        "path": row.get("path") or [],
                    },
                    extra={
                        "event_id": event_id,
                        "event_type": row.get("event_type"),
                        "graph_depth": row.get("depth"),
                        "graph_relationship": row.get("relationship"),
                        "graph_path": row.get("path") or [],
                    },
                )
            )
        return entries

    @staticmethod
    def _content_from_graph_payload(payload: Any) -> str:
        if isinstance(payload, str):
            return payload.strip()
        if not isinstance(payload, dict):
            return ""
        for key in ("summary", "content", "text", "message", "observation", "result"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _redis_candidate_id(query: MemoryQuery) -> str:
        tenant = str(query.tenant_id or "")
        user = str(query.user_id or "")
        session = str(getattr(query, "session_id", None) or "short_term")
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"karen:redis:{tenant}:{user}:{session}"))

    @staticmethod
    def _coerce_datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                return None
        return None

    def _entry(
        self,
        query: MemoryQuery,
        content: str,
        source: str,
        mem_type: MemoryType,
        *,
        semantic: float = 0.0,
        lexical: float = 0.0,
        stable_id: str | None = None,
        timestamp: datetime | None = None,
        confidence: float = 0.8,
        provenance: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        retrieved_at = datetime.utcnow()
        custom = {
            "source_store": source,
            "provenance": provenance
            or {
                "store": source,
                "retrieved_at": retrieved_at.isoformat(),
            },
            "semantic_similarity": semantic,
            "lexical_match": lexical,
            "freshness": 1.0,
            "importance": 0.5,
            "confidence": confidence,
            "reuse_count": 0,
            "memory_class_weight": 1.0,
            "user_confirmation": 0.0,
            "source_trust": 1.0,
            "tenant_match": 1.0,
            "correction_penalty": 0.0,
            "quarantine_penalty": 0.0,
            "procedure_success_rate": 0.0,
        }
        custom.update(extra or {})
        metadata = MemoryMetadata(
            tenant_id=str(query.tenant_id),
            user_id=str(query.user_id),
            conversation_id=getattr(query, "conversation_id", None),
            session_id=getattr(query, "session_id", None),
            source=source,
            custom=custom,
        )
        event_time = timestamp or retrieved_at
        return MemoryEntry(
            id=stable_id or str(uuid.uuid4()),
            content=content,
            memory_type=mem_type,
            namespace=MemoryNamespace.SHORT_TERM if source == "redis" else MemoryNamespace.LONG_TERM,
            timestamp=event_time,
            created_at=event_time,
            updated_at=event_time,
            relevance=max(semantic, lexical),
            confidence=confidence,
            importance=5.0,
            metadata=metadata,
        )


retrieval_router = HybridRetrievalRouter()


def get_retrieval_router() -> HybridRetrievalRouter:
    return retrieval_router
