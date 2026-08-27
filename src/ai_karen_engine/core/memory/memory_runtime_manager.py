"""Canonical memory runtime manager.

The write-side implementation remains behind `_memory_runtime_base` while this
module owns the public MemoryRuntimeManager and its single NeuroRecall read path.
No database or legacy retrieval fallback is allowed from this runtime surface.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ai_karen_engine.core.logging import get_logger

from . import _memory_runtime_base as _base
from .retrieval.neuro_recall import NeuroRecall, RecallRequest, RecallScopeError

logger = get_logger(__name__)


class MemoryRuntimeManager(_base.MemoryRuntimeManager):
    """Memory subsystem authority with one async NeuroRecall read path."""

    def __init__(
        self,
        retrieval_adapter: Any | None = None,
        consolidation_adapter: Any | None = None,
        recall_service: Any | None = None,
    ) -> None:
        if retrieval_adapter is not None:
            logger.warning(
                "memory.retrieval_adapter_ignored",
                extra={"replacement": "NeuroRecall"},
            )
        super().__init__(consolidation_adapter=consolidation_adapter)
        self._neuro_recall = recall_service or self._build_neuro_recall()

    @staticmethod
    def _build_neuro_recall() -> NeuroRecall:
        """Compose scoped source retrievers beneath the one recall authority."""
        from ai_karen_engine.platform.memory.postgres import (
            PostgresProfileRecallRetriever,
            PostgresProceduralRecallRetriever,
            PostgresRecallRetriever,
        )

        from .retrieval.retrieval_router import get_retrieval_router

        return NeuroRecall(
            retrievers=(
                PostgresRecallRetriever(),
                PostgresProfileRecallRetriever(),
                PostgresProceduralRecallRetriever(),
                get_retrieval_router(),
            )
        )

    def set_recall_service(self, service: Any) -> None:
        """Replace the canonical async recall service for tests/adapters."""
        if service is None or not hasattr(service, "recall"):
            raise TypeError("recall service must provide async recall(request)")
        self._neuro_recall = service

    async def recall_context(
        self,
        user_id: Any,
        query: str,
        top_k: int = 10,
        tiers: Sequence[str] | None = None,
        tenant_id: str | None = None,
        include_embeddings: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Recall memory only through NeuroRecall; no direct database fallback."""
        _base._METRICS["recall_requests"] += 1

        resolved_user_id = user_id
        if isinstance(user_id, dict):
            resolved_user_id = user_id.get("user_id") or user_id.get("id")

        if not str(tenant_id or "").strip():
            raise RecallScopeError("tenant_id is required for memory recall")
        if not str(resolved_user_id or "").strip():
            raise RecallScopeError("user_id is required for memory recall")

        request = RecallRequest(
            query=str(query or ""),
            tenant_id=str(tenant_id),
            user_id=str(resolved_user_id),
            top_k=int(top_k or 10),
            conversation_id=kwargs.get("conversation_id"),
            session_id=kwargs.get("session_id"),
            correlation_id=kwargs.get("correlation_id"),
            request_id=kwargs.get("request_id"),
            namespaces=tuple(str(tier) for tier in (tiers or ())),
            metadata={
                "include_embeddings": bool(include_embeddings),
                "latency_budget_ms": kwargs.get("latency_budget_ms"),
            },
        )
        result = await self._neuro_recall.recall(request)

        formatted: list[dict[str, Any]] = []
        for item in result.memories:
            payload = item.to_dict()
            formatted.append(
                {
                    "id": item.id,
                    "content": item.content,
                    "metadata": payload.get("metadata", {}),
                    "timestamp": item.timestamp.timestamp(),
                    "similarity_score": item.relevance,
                    "memory_type": item.memory_type.value,
                    "result": item.content,
                }
            )

        _base._METRICS["recall_hits"] += len(formatted)
        return {
            "results": formatted,
            "status": "degraded" if result.degraded else "success",
            "count": len(formatted),
            "source": "neuro_recall",
            "degraded": result.degraded,
            "degradation_reason": result.degradation_reason,
            "provenance": list(result.provenance),
            "latency_ms": result.latency_ms,
        }


memory_manager = MemoryRuntimeManager()
_base.bind_memory_manager(memory_manager)


def get_memory_manager() -> MemoryRuntimeManager:
    return memory_manager


def init_memory() -> MemoryRuntimeManager:
    logger.info("Initializing canonical memory runtime manager")
    memory_manager._ensure_db_session_factory()
    return memory_manager


async def close() -> None:
    await memory_manager.close()


async def recall_context(
    *,
    user_id: Any,
    tenant_id: str,
    query: str,
    conversation_id: str | None = None,
    session_id: str | None = None,
    top_k: int = 10,
    correlation_id: str | None = None,
    activation: Any | None = None,
    tiers: Sequence[str] | None = None,
    include_embeddings: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    del activation
    return await memory_manager.recall_context(
        user_id=user_id,
        tenant_id=tenant_id,
        query=query,
        conversation_id=conversation_id,
        session_id=session_id,
        top_k=top_k,
        correlation_id=correlation_id,
        tiers=tiers,
        include_embeddings=include_embeddings,
        **kwargs,
    )


update_memory = _base.update_memory
export_promoted_artifacts = _base.export_promoted_artifacts
get_metrics = _base.get_metrics


__all__ = [
    "MemoryRuntimeManager",
    "close",
    "export_promoted_artifacts",
    "get_memory_manager",
    "get_metrics",
    "init_memory",
    "memory_manager",
    "recall_context",
    "update_memory",
]
