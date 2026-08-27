from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.memory.graph.entity_resolution import extract_entity_cues
from ai_karen_engine.core.memory.graph.service import get_leangraph_service
from ai_karen_engine.core.runtime.resilience import get_safe_stage_runner
from ai_karen_engine.platform.memory.postgres.entity_resolver import PostgresEntityResolver
from ai_karen_engine.platform.memory.postgres.event_source import PostgresEventSource
from ai_karen_engine.platform.memory.redis.redis_connection_manager import get_redis_manager

from ..neuro import decide_activation_mode, emit_memory_event
from ..types import MemoryEntry, MemoryMetadata, MemoryNamespace, MemoryQuery, MemoryType

logger = get_logger(__name__)


class HybridRetrievalRouter:
    """Retrieve bounded Redis/graph source candidates for NeuroRecall.

    Source activation may happen here for latency control. Fusion, guardrails,
    deduplication, final ranking, and selection belong exclusively to NeuroRecall.
    """

    def __init__(self) -> None:
        self.safe_runner = get_safe_stage_runner()
        self.redis = get_redis_manager()
        self.leangraph = get_leangraph_service()
        self.event_source = PostgresEventSource()
        self.entity_resolver = PostgresEntityResolver()

    async def recall(self, query: MemoryQuery) -> list[MemoryEntry]:
        started = time.time()
        correlation_id = str(uuid.uuid4())
        tenant_id = str(query.tenant_id or "")
        user_id = str(query.user_id or "")
        if not tenant_id or not user_id:
            logger.warning("memory.source_router.degraded", extra={"reason": "missing_tenant_or_user"})
            return []

        activation = decide_activation_mode(query=query.text or "", latency_budget_ms=300)
        candidates: list[MemoryEntry] = []
        stores: list[str] = []

        if activation.mode.value != "none":
            stores.append("redis")
            candidates.extend(
                await self.safe_runner.run_stage(
                    "memory_fast_recall",
                    "memory_learning_enabled",
                    self._query_redis,
                    query,
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
                or []
            )

        if activation.include_graph:
            stores.append("graph")
            candidates.extend(
                await self.safe_runner.run_stage(
                    "memory_graph_expansion",
                    "memory_learning_enabled",
                    self._query_graph,
                    query,
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
                or []
            )

        emit_memory_event(
            "memory.source_router.completed",
            {
                "correlation_id": correlation_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "memory_activation_mode": activation.mode.value,
                "stores_queried": stores,
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
        candidate_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"karen:redis:{query.tenant_id}:{query.user_id}:{session_id or 'short_term'}",
            )
        )
        return [
            self._entry(
                query,
                id=candidate_id,
                content=content,
                source="redis",
                memory_type=MemoryType.EPISODIC,
                relevance=0.4,
                confidence=0.8,
                provenance={"store": "redis", "session_id": session_id, "ephemeral": True},
            )
        ]

    async def _query_graph(self, query: MemoryQuery) -> list[MemoryEntry]:
        if not query.text:
            return []

        raw_cues = extract_entity_cues(query.text, max_cues=8)
        if not raw_cues:
            return []

        resolution_by_canonical: dict[str, dict[str, Any]] = {}
        try:
            resolved = await self.entity_resolver.resolve_cues(
                tenant_id=str(query.tenant_id),
                user_id=str(query.user_id),
                cues=raw_cues,
                limit=8,
            )
        except Exception as exc:
            logger.warning(
                "memory.entity_resolution.degraded",
                extra={
                    "tenant_id": query.tenant_id,
                    "user_id": query.user_id,
                    "error_type": type(exc).__name__,
                },
            )
            resolved = []

        graph_cues: list[str] = []
        for item in resolved:
            canonical = item.canonical_text.strip()
            if not canonical or canonical.casefold() in {cue.casefold() for cue in graph_cues}:
                continue
            graph_cues.append(canonical)
            resolution_by_canonical[canonical.casefold()] = {
                "entity_id": item.entity_id,
                "matched_text": item.matched_text,
                "match_type": item.match_type,
                "score": item.score,
            }

        # Exact raw cues remain a safe fallback for local/dev databases where the
        # forward pg_trgm migration has not been applied yet.
        for cue in raw_cues:
            if cue.casefold() not in {value.casefold() for value in graph_cues}:
                graph_cues.append(cue)
            if len(graph_cues) >= 8:
                break

        graph_rows_by_event: dict[str, dict[str, Any]] = {}
        try:
            for cue in graph_cues[:8]:
                rows = await self.leangraph.get_entity_context(
                    tenant_id=str(query.tenant_id),
                    user_id=str(query.user_id),
                    entity_text=cue,
                    limit=min(10, max(2, query.top_k)),
                )
                for row in rows or []:
                    event_id = str(row.get("event_id") or "").strip()
                    if not event_id:
                        continue
                    existing = graph_rows_by_event.get(event_id)
                    enriched = dict(row)
                    enriched["matched_entity_cue"] = cue
                    enriched["entity_resolution"] = resolution_by_canonical.get(cue.casefold())
                    if existing is None or int(enriched.get("depth") or 999) < int(existing.get("depth") or 999):
                        graph_rows_by_event[event_id] = enriched
                    if len(graph_rows_by_event) >= min(40, max(4, query.top_k * 4)):
                        break
                if len(graph_rows_by_event) >= min(40, max(4, query.top_k * 4)):
                    break
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

        graph_rows = list(graph_rows_by_event.values())
        event_map = await self.event_source.fetch_many(
            tenant_id=str(query.tenant_id),
            user_id=str(query.user_id),
            event_ids=graph_rows_by_event,
        )

        entries: list[MemoryEntry] = []
        for graph_row in graph_rows:
            event_id = str(graph_row.get("event_id") or "").strip()
            source = event_map.get(event_id)
            if source is None:
                continue
            content = self._payload_content(source.get("payload"))
            if not content:
                continue

            depth = int(graph_row.get("depth") or 1)
            graph_relevance = max(0.15, min(0.75, 0.75 - (depth - 1) * 0.12))
            entries.append(
                self._entry(
                    query,
                    id=event_id,
                    content=content,
                    source="postgres_graph",
                    memory_type=MemoryType.EPISODIC,
                    relevance=graph_relevance,
                    confidence=float(source.get("confidence") or 0.0),
                    timestamp=source.get("created_at"),
                    provenance={
                        "store": "postgres",
                        "record_type": "memory_event",
                        "event_id": event_id,
                        "source_type": source.get("source_type"),
                        "source_ref": source.get("source_ref"),
                        "matched_entity_cue": graph_row.get("matched_entity_cue"),
                        "entity_resolution": graph_row.get("entity_resolution"),
                        "graph_relationship": graph_row.get("relationship"),
                        "graph_depth": depth,
                        "graph_path": graph_row.get("path") or [],
                    },
                    custom={
                        "event_id": event_id,
                        "event_type": source.get("event_type"),
                        "valid_from": self._iso(source.get("valid_from")),
                        "valid_to": self._iso(source.get("valid_to")),
                        "matched_entity_cue": graph_row.get("matched_entity_cue"),
                        "entity_resolution": graph_row.get("entity_resolution"),
                        "graph_depth": depth,
                        "graph_relationship": graph_row.get("relationship"),
                        "graph_path": graph_row.get("path") or [],
                    },
                )
            )
        return entries

    def _entry(
        self,
        query: MemoryQuery,
        *,
        id: str,
        content: str,
        source: str,
        memory_type: MemoryType,
        relevance: float,
        confidence: float,
        provenance: dict[str, Any],
        timestamp: datetime | None = None,
        custom: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        event_time = timestamp or datetime.utcnow()
        metadata_custom = {
            "source_store": source,
            "provenance": provenance,
            "semantic_similarity": relevance if source == "postgres_graph" else 0.0,
            "lexical_match": relevance if source == "redis" else 0.0,
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
        metadata_custom.update(custom or {})
        metadata = MemoryMetadata(
            tenant_id=str(query.tenant_id),
            user_id=str(query.user_id),
            conversation_id=getattr(query, "conversation_id", None),
            session_id=getattr(query, "session_id", None),
            source=source,
            custom=metadata_custom,
        )
        return MemoryEntry(
            id=id,
            content=content,
            memory_type=memory_type,
            namespace=MemoryNamespace.SHORT_TERM if source == "redis" else MemoryNamespace.LONG_TERM,
            timestamp=event_time,
            created_at=event_time,
            updated_at=event_time,
            relevance=relevance,
            confidence=confidence,
            importance=5.0,
            metadata=metadata,
        )

    @staticmethod
    def _payload_content(payload: Any) -> str:
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
    def _iso(value: Any) -> str | None:
        return value.isoformat() if hasattr(value, "isoformat") else None


retrieval_router = HybridRetrievalRouter()


def get_retrieval_router() -> HybridRetrievalRouter:
    return retrieval_router
