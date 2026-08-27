from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Any, Protocol

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.memory.graph.entity_resolution import extract_entity_cues
from ai_karen_engine.core.memory.stm import STMScope, STMSlot, STMPort
from ai_karen_engine.core.runtime.resilience import get_safe_stage_runner

from ..neuro import decide_activation_mode, emit_memory_event
from ..types import MemoryEntry, MemoryMetadata, MemoryNamespace, MemoryQuery, MemoryType

logger = get_logger(__name__)


class GraphContextSource(Protocol):
    async def get_entity_context(
        self,
        *,
        tenant_id: str,
        user_id: str,
        entity_text: str,
        limit: int,
    ) -> list[dict[str, Any]]: ...


class EventSource(Protocol):
    async def fetch_many(
        self,
        *,
        tenant_id: str,
        user_id: str,
        event_ids: Any,
    ) -> dict[str, dict[str, Any]]: ...


class EntityResolver(Protocol):
    async def resolve_cues(
        self,
        *,
        tenant_id: str,
        user_id: str,
        cues: list[str],
        limit: int,
    ) -> list[Any]: ...


class HybridRetrievalRouter:
    """Retrieve bounded STM/graph candidates for NeuroRecall.

    The router coordinates source activation only. It never constructs storage
    backends and never owns fusion, guardrails, deduplication, final ranking, or
    selection. Those remain NeuroRecall authority.
    """

    STM_RECALL_SLOTS = (
        STMSlot.RECENT_CONTEXT,
        STMSlot.ACTIVE_EPISODE,
        STMSlot.ACTIVE_GOAL,
        STMSlot.ACTIVE_PROJECT,
        STMSlot.WORKING_STATE,
    )

    def __init__(
        self,
        *,
        stm: STMPort,
        graph: GraphContextSource,
        event_source: EventSource,
        entity_resolver: EntityResolver,
    ) -> None:
        self.safe_runner = get_safe_stage_runner()
        self.stm = stm
        self.graph = graph
        self.event_source = event_source
        self.entity_resolver = entity_resolver

    async def recall(self, query: MemoryQuery) -> list[MemoryEntry]:
        started = time.time()
        correlation_id = str(uuid.uuid4())
        tenant_id = str(query.tenant_id or "").strip()
        user_id = str(query.user_id or "").strip()
        if not tenant_id or not user_id or tenant_id == "default":
            logger.warning(
                "memory.source_router.degraded",
                extra={"reason": "invalid_tenant_or_user_scope"},
            )
            return []

        activation = decide_activation_mode(query=query.text or "", latency_budget_ms=300)
        candidates: list[MemoryEntry] = []
        stores: list[str] = []

        if activation.mode.value != "none":
            stores.append("stm")
            candidates.extend(
                await self.safe_runner.run_stage(
                    "memory_stm_recall",
                    "memory_learning_enabled",
                    self._query_stm,
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
                "stm_degraded": self.stm.degraded(),
                "latency_ms": (time.time() - started) * 1000,
            },
        )
        return candidates

    async def _query_stm(self, query: MemoryQuery) -> list[MemoryEntry]:
        session_id = str(getattr(query, "session_id", None) or "").strip()
        if not session_id:
            return []

        try:
            scope = STMScope(
                tenant_id=str(query.tenant_id),
                user_id=str(query.user_id),
                session_id=session_id,
            )
            scope.validate()
        except ValueError:
            return []

        entries: list[MemoryEntry] = []
        for slot in self.STM_RECALL_SLOTS:
            try:
                data = await self.stm.get_slot(scope=scope, slot=slot)
            except Exception as exc:
                logger.warning(
                    "memory.stm_recall.failed",
                    extra={
                        "tenant_id": query.tenant_id,
                        "user_id": query.user_id,
                        "session_id": session_id,
                        "stm_slot": slot.value,
                        "error_type": type(exc).__name__,
                    },
                )
                continue
            if not data:
                continue

            content = self._stm_content(slot, data)
            if not content:
                continue
            candidate_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"karen:stm:{query.tenant_id}:{query.user_id}:{session_id}:{slot.value}",
                )
            )
            entries.append(
                self._entry(
                    query,
                    id=candidate_id,
                    content=content,
                    source="stm",
                    memory_type=self._stm_memory_type(slot),
                    relevance=self._stm_relevance(slot),
                    confidence=0.8,
                    provenance={
                        "store": "stm",
                        "session_id": session_id,
                        "stm_slot": slot.value,
                        "ephemeral": True,
                    },
                    custom={
                        "stm_slot": slot.value,
                        "ephemeral": True,
                        "current_goal_relevance": 1.0
                        if slot == STMSlot.ACTIVE_GOAL
                        else 0.0,
                    },
                )
            )
        return entries

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
            canonical = str(getattr(item, "canonical_text", "") or "").strip()
            if not canonical or canonical.casefold() in {
                cue.casefold() for cue in graph_cues
            }:
                continue
            graph_cues.append(canonical)
            resolution_by_canonical[canonical.casefold()] = {
                "entity_id": getattr(item, "entity_id", None),
                "matched_text": getattr(item, "matched_text", None),
                "match_type": getattr(item, "match_type", None),
                "score": getattr(item, "score", None),
            }

        for cue in raw_cues:
            if cue.casefold() not in {value.casefold() for value in graph_cues}:
                graph_cues.append(cue)
            if len(graph_cues) >= 8:
                break

        graph_rows_by_event: dict[str, dict[str, Any]] = {}
        try:
            for cue in graph_cues[:8]:
                rows = await self.graph.get_entity_context(
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
                    enriched["entity_resolution"] = resolution_by_canonical.get(
                        cue.casefold()
                    )
                    if existing is None or int(enriched.get("depth") or 999) < int(
                        existing.get("depth") or 999
                    ):
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
            "lexical_match": 0.0,
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
            namespace=MemoryNamespace.SHORT_TERM
            if source == "stm"
            else MemoryNamespace.LONG_TERM,
            timestamp=event_time,
            created_at=event_time,
            updated_at=event_time,
            relevance=relevance,
            confidence=confidence,
            importance=5.0,
            metadata=metadata,
        )

    @staticmethod
    def _stm_memory_type(slot: STMSlot) -> MemoryType:
        if slot in {STMSlot.ACTIVE_EPISODE, STMSlot.RECENT_CONTEXT}:
            return MemoryType.EPISODIC
        return MemoryType.SEMANTIC

    @staticmethod
    def _stm_relevance(slot: STMSlot) -> float:
        weights = {
            STMSlot.ACTIVE_GOAL: 0.8,
            STMSlot.ACTIVE_PROJECT: 0.75,
            STMSlot.RECENT_CONTEXT: 0.7,
            STMSlot.ACTIVE_EPISODE: 0.7,
            STMSlot.WORKING_STATE: 0.55,
        }
        return weights.get(slot, 0.5)

    @staticmethod
    def _stm_content(slot: STMSlot, data: dict[str, Any]) -> str:
        if slot == STMSlot.RECENT_CONTEXT:
            latest = data.get("latest")
            if isinstance(latest, dict):
                for key in ("content", "summary", "text", "last_text"):
                    value = latest.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        if slot == STMSlot.ACTIVE_EPISODE:
            value = data.get("last_text")
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("content", "summary", "text", "name", "goal", "project", "value"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        try:
            return json.dumps(data, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return ""

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


__all__ = [
    "EntityResolver",
    "EventSource",
    "GraphContextSource",
    "HybridRetrievalRouter",
]
