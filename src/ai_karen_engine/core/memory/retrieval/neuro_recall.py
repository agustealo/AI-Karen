"""Canonical async NeuroRecall service.

NeuroRecall owns memory-retrieval strategy, candidate governance, fusion,
deduplication, final ranking, and selection. Source retrievers only produce
scoped candidates. NeuroRecall does not persist memory, select providers/models,
build prompts, or execute tools.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.memory.neuro import (
    MemoryCandidate,
    MemoryClass,
    classify_memory_candidate,
    evaluate_guardrails,
)
from ai_karen_engine.core.memory.neuro.scoring import blended_score
from ai_karen_engine.core.memory.types import MemoryEntry, MemoryQuery

logger = get_logger(__name__)

DEFAULT_RECALL_LATENCY_BUDGET_MS = 300
MAX_RECALL_LATENCY_BUDGET_MS = 5_000


class RecallScopeError(ValueError):
    """Raised when a recall request lacks mandatory isolation scope."""


@dataclass(frozen=True, slots=True)
class RecallRequest:
    query: str
    tenant_id: str
    user_id: str
    top_k: int = 10
    conversation_id: str | None = None
    session_id: str | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    namespaces: tuple[str, ...] = ()
    latency_budget_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        resolved_tenant = str(self.tenant_id or "").strip()
        if not resolved_tenant or resolved_tenant == "default":
            raise RecallScopeError(
                "explicit non-default tenant_id is required for memory recall"
            )
        if not str(self.user_id or "").strip():
            raise RecallScopeError("user_id is required for memory recall")
        if not str(self.query or "").strip():
            raise RecallScopeError("query is required for memory recall")
        if self.top_k < 1:
            raise RecallScopeError("top_k must be greater than zero")
        if self.latency_budget_ms is not None and self.latency_budget_ms < 1:
            raise RecallScopeError("latency_budget_ms must be greater than zero")

    def resolved_latency_budget_ms(self) -> int:
        """Return a bounded deadline while preserving legacy metadata callers."""
        raw_budget: Any = self.latency_budget_ms
        if raw_budget is None:
            raw_budget = self.metadata.get("latency_budget_ms")
        if raw_budget is None:
            return DEFAULT_RECALL_LATENCY_BUDGET_MS
        try:
            budget = int(raw_budget)
        except (TypeError, ValueError):
            return DEFAULT_RECALL_LATENCY_BUDGET_MS
        return min(max(budget, 1), MAX_RECALL_LATENCY_BUDGET_MS)


@dataclass(frozen=True, slots=True)
class RecallResult:
    memories: tuple[MemoryEntry, ...]
    tenant_id: str
    user_id: str
    query: str
    latency_ms: float
    degraded: bool = False
    degradation_reason: str | None = None
    provenance: tuple[dict[str, Any], ...] = ()


@runtime_checkable
class RecallRetriever(Protocol):
    async def recall(self, query: MemoryQuery) -> list[MemoryEntry]: ...


class NeuroRecall:
    """Single production recall strategy and selection authority."""

    def __init__(
        self,
        retriever: RecallRetriever | None = None,
        *,
        retrievers: Sequence[RecallRetriever] | None = None,
    ) -> None:
        if retriever is not None and retrievers is not None:
            raise TypeError("provide retriever or retrievers, not both")

        if retrievers is not None:
            selected = tuple(retrievers)
        elif retriever is not None:
            selected = (retriever,)
        else:
            from .retrieval_router import get_retrieval_router

            selected = (get_retrieval_router(),)

        if not selected:
            raise ValueError("NeuroRecall requires at least one retriever")
        for candidate in selected:
            if not hasattr(candidate, "recall"):
                raise TypeError("every NeuroRecall retriever must provide async recall(query)")
        self._retrievers = selected

    async def recall(self, request: RecallRequest) -> RecallResult:
        request.validate()
        started = time.perf_counter()
        effective_top_k = min(max(int(request.top_k), 1), 100)
        latency_budget_ms = request.resolved_latency_budget_ms()

        query = MemoryQuery(
            text=request.query,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            session_id=request.session_id,
            top_k=effective_top_k,
        )

        try:
            raw_results = await asyncio.wait_for(
                asyncio.gather(
                    *(retriever.recall(query) for retriever in self._retrievers),
                    return_exceptions=True,
                ),
                timeout=latency_budget_ms / 1000.0,
            )
        except TimeoutError:
            latency_ms = (time.perf_counter() - started) * 1000
            logger.warning(
                "memory.neuro_recall.deadline_exceeded",
                extra={
                    "tenant_id": request.tenant_id,
                    "user_id": request.user_id,
                    "correlation_id": request.correlation_id,
                    "request_id": request.request_id,
                    "retriever_count": len(self._retrievers),
                    "latency_budget_ms": latency_budget_ms,
                    "latency_ms": latency_ms,
                },
            )
            return RecallResult(
                memories=(),
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                query=request.query,
                latency_ms=latency_ms,
                degraded=True,
                degradation_reason="recall_deadline_exceeded",
                provenance=(),
            )

        failures: list[BaseException] = []
        raw_candidates: list[MemoryEntry] = []
        for index, value in enumerate(raw_results):
            if isinstance(value, BaseException):
                if isinstance(value, RecallScopeError):
                    raise value
                failures.append(value)
                logger.warning(
                    "memory.neuro_recall.retriever_failed",
                    extra={
                        "tenant_id": request.tenant_id,
                        "user_id": request.user_id,
                        "correlation_id": request.correlation_id,
                        "request_id": request.request_id,
                        "retriever_index": index,
                        "retriever_type": type(self._retrievers[index]).__name__,
                        "error_type": type(value).__name__,
                    },
                )
                continue
            raw_candidates.extend(value)

        if failures and not raw_candidates:
            return RecallResult(
                memories=(),
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                query=request.query,
                latency_ms=(time.perf_counter() - started) * 1000,
                degraded=True,
                degradation_reason="retrieval_unavailable",
                provenance=(),
            )

        selected_by_id: dict[str, MemoryEntry] = {}
        provenance_by_id: dict[str, dict[str, Any]] = {}
        rejected_count = 0

        for memory in raw_candidates:
            metadata = getattr(memory, "metadata", None)
            memory_tenant = getattr(metadata, "tenant_id", None) if metadata else None
            memory_user = getattr(metadata, "user_id", None) if metadata else None
            if str(memory_tenant or "") != request.tenant_id:
                rejected_count += 1
                continue
            if str(memory_user or "") != request.user_id:
                rejected_count += 1
                continue

            candidate = self._to_candidate(memory, request)
            guard = evaluate_guardrails(candidate)
            if guard.outcome.value in {"reject", "quarantine"}:
                rejected_count += 1
                continue

            memory.relevance = blended_score(candidate)
            custom = getattr(metadata, "custom", {}) if metadata else {}
            if isinstance(custom, dict):
                custom["memory_class"] = candidate.memory_class.value
                custom["reason_selected"] = "neuro_recall_rank"
                custom["used_in_prompt"] = False
                custom["guard_outcome"] = guard.outcome.value
                if guard.reasons:
                    custom["guard_reasons"] = list(guard.reasons)

            memory_id = str(memory.id)
            previous = selected_by_id.get(memory_id)
            if previous is None or self._sort_key(memory) > self._sort_key(previous):
                selected_by_id[memory_id] = memory
                provenance = custom.get("provenance", {}) if isinstance(custom, dict) else {}
                provenance_by_id[memory_id] = {
                    "memory_id": memory_id,
                    "source": getattr(metadata, "source", None) if metadata else None,
                    "source_store": custom.get("source_store") if isinstance(custom, dict) else None,
                    "memory_class": candidate.memory_class.value,
                    "provenance": provenance if isinstance(provenance, dict) else {},
                    "correlation_id": request.correlation_id,
                }

        ranked = sorted(selected_by_id.values(), key=self._sort_key, reverse=True)
        selected = ranked[:effective_top_k]
        provenance = tuple(provenance_by_id[str(item.id)] for item in selected)

        degraded = bool(failures)
        degradation_reason = "partial_retrieval_failure" if failures else None
        logger.info(
            "memory.neuro_recall.completed",
            extra={
                "tenant_id": request.tenant_id,
                "user_id": request.user_id,
                "correlation_id": request.correlation_id,
                "request_id": request.request_id,
                "retriever_count": len(self._retrievers),
                "failed_retriever_count": len(failures),
                "raw_candidate_count": len(raw_candidates),
                "rejected_candidate_count": rejected_count,
                "deduped_candidate_count": len(ranked),
                "result_count": len(selected),
                "degraded": degraded,
                "latency_budget_ms": latency_budget_ms,
            },
        )
        return RecallResult(
            memories=tuple(selected),
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            query=request.query,
            latency_ms=(time.perf_counter() - started) * 1000,
            degraded=degraded,
            degradation_reason=degradation_reason,
            provenance=provenance,
        )

    @staticmethod
    def _to_candidate(memory: MemoryEntry, request: RecallRequest) -> MemoryCandidate:
        metadata = memory.metadata
        custom = metadata.custom if metadata and isinstance(metadata.custom, dict) else {}
        source = str(custom.get("source_store") or (metadata.source if metadata else "unknown"))
        candidate = MemoryCandidate(
            id=str(memory.id),
            text=str(memory.content or ""),
            memory_class=MemoryClass.EPISODIC,
            source=source,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            confidence=float(memory.confidence or 0.0),
            importance=float(memory.importance or 0.0) / 10.0,
            freshness=float(custom.get("freshness", 1.0) or 1.0),
            provenance=custom.get("provenance", {}) if isinstance(custom.get("provenance", {}), dict) else {},
            created_at=memory.created_at,
            updated_at=memory.updated_at,
            expires_at=memory.expires_at,
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

    @staticmethod
    def _sort_key(item: MemoryEntry) -> tuple[float, float, float]:
        timestamp = getattr(item, "timestamp", None)
        try:
            timestamp_value = float(timestamp.timestamp()) if timestamp is not None else 0.0
        except (AttributeError, OSError, OverflowError, TypeError, ValueError):
            timestamp_value = 0.0
        return (
            float(getattr(item, "relevance", 0.0) or 0.0),
            float(getattr(item, "confidence", 0.0) or 0.0),
            timestamp_value,
        )


__all__ = [
    "DEFAULT_RECALL_LATENCY_BUDGET_MS",
    "MAX_RECALL_LATENCY_BUDGET_MS",
    "NeuroRecall",
    "RecallRequest",
    "RecallResult",
    "RecallRetriever",
    "RecallScopeError",
]
