"""Canonical async NeuroRecall service.

NeuroRecall owns memory-retrieval strategy and selection. It does not persist
memory and it does not select providers/models, build prompts, or execute tools.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.memory.types import MemoryEntry, MemoryQuery

logger = get_logger(__name__)


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
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not str(self.tenant_id or "").strip():
            raise RecallScopeError("tenant_id is required for memory recall")
        if not str(self.user_id or "").strip():
            raise RecallScopeError("user_id is required for memory recall")
        if not str(self.query or "").strip():
            raise RecallScopeError("query is required for memory recall")
        if self.top_k < 1:
            raise RecallScopeError("top_k must be greater than zero")


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
    """Single production recall strategy service for the memory domain."""

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

        query = MemoryQuery(
            text=request.query,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            top_k=effective_top_k,
        )

        raw_results = await asyncio.gather(
            *(retriever.recall(query) for retriever in self._retrievers),
            return_exceptions=True,
        )

        failures: list[BaseException] = []
        memories: list[MemoryEntry] = []
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
            memories.extend(value)

        if failures and not memories:
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

        scoped: list[MemoryEntry] = []
        provenance_by_id: dict[str, dict[str, Any]] = {}
        for memory in memories:
            metadata = getattr(memory, "metadata", None)
            memory_tenant = getattr(metadata, "tenant_id", None) if metadata else None
            memory_user = getattr(metadata, "user_id", None) if metadata else None

            # Defense in depth: retrievers must scope upstream, and NeuroRecall
            # independently rejects results that cannot prove the same scope.
            if str(memory_tenant or "") != request.tenant_id:
                continue
            if str(memory_user or "") != request.user_id:
                continue

            memory_id = str(memory.id)
            if memory_id in provenance_by_id:
                continue

            scoped.append(memory)
            custom = getattr(metadata, "custom", {}) if metadata else {}
            provenance_by_id[memory_id] = {
                "memory_id": memory_id,
                "source": getattr(metadata, "source", None) if metadata else None,
                "source_store": custom.get("source_store") if isinstance(custom, dict) else None,
                "correlation_id": request.correlation_id,
            }

        scoped.sort(
            key=lambda item: (
                float(getattr(item, "relevance", 0.0) or 0.0),
                float(getattr(item, "confidence", 0.0) or 0.0),
                getattr(item, "timestamp", None),
            ),
            reverse=True,
        )
        selected = scoped[:effective_top_k]
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
                "result_count": len(selected),
                "degraded": degraded,
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


__all__ = [
    "NeuroRecall",
    "RecallRequest",
    "RecallResult",
    "RecallRetriever",
    "RecallScopeError",
]
