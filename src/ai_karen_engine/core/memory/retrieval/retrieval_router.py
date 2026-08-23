from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from ai_karen_engine.clients.database.elastic_client import ElasticClient
from ai_karen_engine.clients.database.milvus_client import MilvusClient
from ai_karen_engine.core.memory.redis_connection_manager import get_redis_manager
from ai_karen_engine.core.memory.graph.service import get_leangraph_service
from ai_karen_engine.core.runtime.resilience import get_safe_stage_runner

from ..neuro import (
    MemoryCandidate,
    MemoryClass,
    classify_memory_candidate,
    decide_activation_mode,
    evaluate_guardrails,
    emit_memory_event,
)
from ..neuro.scoring import blended_score
from ..types import MemoryEntry, MemoryMetadata, MemoryNamespace, MemoryQuery, MemoryType
from .fusion import dedupe_by_id, reciprocal_rank_fusion
from .rerank import rerank_entries

from ai_karen_engine.core.logging import get_logger
logger = get_logger(__name__)


class HybridRetrievalRouter:
    def __init__(self) -> None:
        self.safe_runner = get_safe_stage_runner()
        self.milvus = MilvusClient(collection="memory_ledger_semantic")
        self.elastic = ElasticClient(index="memory_ledger_lexical")
        self.redis = get_redis_manager()
        self.leangraph = get_leangraph_service()

    async def recall(self, query: MemoryQuery) -> List[MemoryEntry]:
        start = time.time()
        correlation_id = str(uuid.uuid4())
        emit_memory_event("memory.recall.started", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id, "stores_queried": ["redis", "milvus", "elasticsearch"]})
        if not query.tenant_id or not query.user_id:
            logger.warning("memory.recall.degraded", extra={"reason": "missing_tenant_or_user"})
            emit_memory_event("memory.recall.degraded", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id, "degraded": True, "degradation_reason": "missing_tenant_or_user"})
            return []

        emit_memory_event("memory.activation.started", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id})
        activation = decide_activation_mode(query=query.text or "", latency_budget_ms=300)
        emit_memory_event("memory.activation.completed", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id, "memory_activation_mode": activation.mode.value, "token_budget": activation.top_k})

        should_query_semantic = activation.mode.value in {"fast", "deep", "graph", "profile"}
        should_query_lexical = activation.mode.value in {"fast", "deep", "procedural", "profile"}
        hot: List[MemoryEntry] = []
        dense: List[MemoryEntry] = []
        lexical: List[MemoryEntry] = []
        if activation.mode.value != "none":
            emit_memory_event("memory.recall.store.started", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id, "stores_queried": ["redis"]})
            hot = await self.safe_runner.run_stage(
                "memory_fast_recall", "memory_learning_enabled", self._query_redis, query, tenant_id=str(query.tenant_id), user_id=str(query.user_id)
            ) or []
            emit_memory_event("memory.recall.store.completed", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id, "stores_queried": ["redis"], "result_count": len(hot)})
        store_tasks = []
        stores = []
        if should_query_semantic:
            stores.append("milvus")
            store_tasks.append(asyncio.create_task(self.safe_runner.run_stage("memory_dense_recall", "memory_learning_enabled", self._query_milvus, query, tenant_id=str(query.tenant_id), user_id=str(query.user_id))))
        if should_query_lexical:
            stores.append("elasticsearch")
            store_tasks.append(asyncio.create_task(self.safe_runner.run_stage("memory_lexical_recall", "memory_learning_enabled", self._query_elastic, query, tenant_id=str(query.tenant_id), user_id=str(query.user_id))))
        if stores:
            emit_memory_event("memory.recall.store.started", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id, "stores_queried": stores})
            store_results = await asyncio.gather(*store_tasks)
            if should_query_semantic:
                dense = (store_results[0] if store_results else []) or []
            if should_query_lexical:
                lexical = (store_results[-1] if store_results else []) or []
            emit_memory_event("memory.recall.store.completed", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id, "stores_queried": stores, "result_count": len(dense) + len(lexical)})

        graph: List[MemoryEntry] = []
        if activation.include_graph:
            emit_memory_event("memory.recall.store.started", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id, "stores_queried": ["graph"]})
            graph = await self.safe_runner.run_stage(
                "memory_graph_expansion",
                "memory_learning_enabled",
                self._query_graph,
                query,
                tenant_id=str(query.tenant_id),
                user_id=str(query.user_id),
            ) or []
            emit_memory_event("memory.recall.store.completed", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id, "stores_queried": ["graph"], "result_count": len(graph)})

        emit_memory_event("memory.profile.started", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id})
        profile = await self._query_profile(query) if activation.include_profile else []
        emit_memory_event("memory.profile.completed", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id, "result_count": len(profile)})
        emit_memory_event("memory.procedural.started", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id})
        procedural = await self._query_procedural(query) if activation.include_procedural else []
        emit_memory_event("memory.procedural.completed", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id, "result_count": len(procedural)})

        fused = reciprocal_rank_fusion({
            "hot": hot,
            "dense": dense,
            "lexical": lexical,
            "graph": graph,
            "profile": profile,
            "procedural": procedural,
        })
        emit_memory_event("memory.recall.fusion.completed", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id, "result_count": len(fused)})

        guarded: List[MemoryEntry] = []
        for e in dedupe_by_id(fused):
            candidate = self._to_candidate(e, query)
            emit_memory_event("memory.guard.started", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id, "memory_classes": [candidate.memory_class.value]})
            guard = evaluate_guardrails(candidate)
            emit_memory_event("memory.guard.completed", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id, "memory_classes": [candidate.memory_class.value], "degraded": guard.outcome.value in {"reject", "quarantine"}, "degradation_reason": ",".join(guard.reasons) if guard.reasons else None})
            if guard.outcome.value in {"reject", "quarantine"}:
                continue
            e.relevance = blended_score(candidate)
            if e.metadata:
                e.metadata.custom["reason_selected"] = "fused_rank"
                e.metadata.custom["used_in_prompt"] = False
            guarded.append(e)

        ranked = rerank_entries(guarded, query.top_k)
        if not ranked:
            emit_memory_event("memory.recall.degraded", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id, "degraded": True, "degradation_reason": "no_results_after_guardrails"})
        logger.info(
            "memory.recall.completed",
            extra={
                "tenant_id": query.tenant_id,
                "user_id": query.user_id,
                "count": len(ranked),
                "latency_ms": (time.time() - start) * 1000,
                "activation_mode": activation.mode.value,
            },
        )
        emit_memory_event("memory.recall.completed", {"correlation_id": correlation_id, "tenant_id": query.tenant_id, "user_id": query.user_id, "memory_activation_mode": activation.mode.value, "stores_queried": ["redis", "milvus", "elasticsearch"] + (["graph"] if activation.include_graph else []), "result_count": len(fused), "selected_count": len(ranked)})
        return ranked

    async def _query_redis(self, query: MemoryQuery) -> List[MemoryEntry]:
        data = await self.redis.get_session(str(query.tenant_id), str(query.user_id), session_id=query.session_id)
        if not data:
            data = await self.redis.get_short_term(str(query.tenant_id), str(query.user_id))
        if not data:
            return []
        content = str(data.get("summary") or data.get("last_message") or data)
        return [self._entry(query, content, "redis", MemoryType.EPISODIC, semantic=0.3, lexical=0.4)]

    async def _query_milvus(self, query: MemoryQuery) -> List[MemoryEntry]:
        try:
            hits = self.milvus.search(query.text or "", tenant_id=str(query.tenant_id), user_id=str(query.user_id), top_k=query.top_k * 2)
        except Exception:
            return []
        out: List[MemoryEntry] = []
        for h in hits or []:
            out.append(self._entry(query, str(h.get("content") or h.get("text") or ""), "milvus", MemoryType.SEMANTIC, semantic=float(h.get("score", 0.6))))
        return out

    async def _query_elastic(self, query: MemoryQuery) -> List[MemoryEntry]:
        hits = self.elastic.search(user_id=str(query.user_id), query=str(query.text or ""), limit=query.top_k * 2, tenant_id=str(query.tenant_id))
        return [self._entry(query, str(h.get("result") or h.get("query") or ""), "elasticsearch", MemoryType.EPISODIC, lexical=0.7) for h in hits]

    async def _query_graph(self, query: MemoryQuery) -> List[MemoryEntry]:
        if not query.text:
            return []
        try:
            results = await self.leangraph.get_entity_context(
                tenant_id=str(query.tenant_id),
                user_id=str(query.user_id),
                entity_text=query.text,
                limit=min(10, query.top_k * 2),
            )
        except Exception:
            return []
        return [self._entry(query, str(r), "graph", MemoryType.SEMANTIC, semantic=0.65) for r in (results or [])]

    async def _query_profile(self, query: MemoryQuery) -> List[MemoryEntry]:
        return []

    async def _query_procedural(self, query: MemoryQuery) -> List[MemoryEntry]:
        return []

    def _entry(self, query: MemoryQuery, content: str, source: str, mem_type: MemoryType, *, semantic: float = 0.0, lexical: float = 0.0) -> MemoryEntry:
        metadata = MemoryMetadata(
            tenant_id=str(query.tenant_id),
            user_id=str(query.user_id),
            conversation_id=getattr(query, "conversation_id", None),
            session_id=getattr(query, "session_id", None),
            source=source,
            custom={
                "source_store": source,
                "provenance": {"store": source, "retrieved_at": datetime.utcnow().isoformat(), "query": query.text or ""},
                "semantic_similarity": semantic,
                "lexical_match": lexical,
                "freshness": 1.0,
                "importance": 0.5,
                "confidence": 0.8,
                "reuse_count": 0,
                "memory_class_weight": 1.0,
                "user_confirmation": 0.0,
                "source_trust": 1.0,
                "tenant_match": 1.0,
                "correction_penalty": 0.0,
                "quarantine_penalty": 0.0,
                "procedure_success_rate": 0.0,
            },
        )
        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            content=content,
            memory_type=mem_type,
            namespace=MemoryNamespace.SHORT_TERM if source == "redis" else MemoryNamespace.LONG_TERM,
            timestamp=datetime.utcnow(),
            relevance=max(semantic, lexical),
            confidence=0.8,
            importance=5.0,
            metadata=metadata,
        )
        return entry

    def _to_candidate(self, entry: MemoryEntry, query: MemoryQuery) -> MemoryCandidate:
        custom = entry.metadata.custom if entry.metadata else {}
        candidate = MemoryCandidate(
            id=entry.id,
            text=entry.content,
            memory_class=MemoryClass.EPISODIC,
            source=str(custom.get("source_store", "unknown")),
            tenant_id=str(query.tenant_id),
            user_id=str(query.user_id),
            confidence=entry.confidence,
            importance=entry.importance / 10.0,
            freshness=float(custom.get("freshness", 1.0)),
            provenance=custom.get("provenance", {}),
            metadata=custom,
        )
        candidate.memory_class = classify_memory_candidate(candidate)
        candidate.metadata["memory_class"] = candidate.memory_class.value
        candidate.metadata["memory_class_weight"] = {
            "stm": 1.0,
            "episodic": 0.95,
            "semantic": 1.0,
            "procedural": 0.9,
            "lesson": 0.8,
            "quarantine": 0.2,
        }.get(candidate.memory_class.value, 1.0)
        return candidate


retrieval_router = HybridRetrievalRouter()


def get_retrieval_router() -> HybridRetrievalRouter:
    return retrieval_router
