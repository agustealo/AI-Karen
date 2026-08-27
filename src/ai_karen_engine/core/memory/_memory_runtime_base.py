"""Minimal backend-neutral base for the canonical memory runtime.

This module contains compatibility bookkeeping only. It does not own recall,
SQL persistence, projections, consent, retention, or provider execution.
Canonical durable writes belong to MemoryFormationService -> NeuroVault.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ai_karen_engine.core.memory.scoring import MemoryWorthinessScorer
from ai_karen_engine.core.memory.signals import get_signal_pipeline
from ai_karen_engine.core.runtime.resilience import (
    get_feature_flags,
    get_resilience_health_monitor,
)

_METRICS: dict[str, int] = {
    "interactions_processed": 0,
    "signals_extracted": 0,
    "signals_admitted": 0,
    "ledger_writes": 0,
    "projection_failures": 0,
    "recall_requests": 0,
    "recall_hits": 0,
    "shadow_mode_runs": 0,
}

_memory_manager: Any | None = None


class MemoryRuntimeManager:
    """Compatibility base with no persistence or recall authority."""

    def __init__(self, consolidation_adapter: Any | None = None) -> None:
        self.flags = get_feature_flags()
        self.signal_pipeline = get_signal_pipeline()
        self.worthiness_scorer = MemoryWorthinessScorer()
        self._consolidation_adapter = consolidation_adapter

    def set_recall_service(self, service: Any) -> None:
        del service
        raise RuntimeError("memory base cannot own recall; use NeuroRecall")

    def set_retrieval_adapter(self, adapter: Any) -> None:
        del adapter
        raise RuntimeError("memory base cannot own retrieval; use NeuroRecall")

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
        del user_id, query, top_k, tiers, tenant_id, include_embeddings, kwargs
        raise RuntimeError("memory base cannot recall; use canonical NeuroRecall")

    async def process_interaction(
        self,
        text: str,
        tenant_id: str,
        user_id: str,
        source_type: str = "chat",
        source_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Evaluate a disabled/shadow interaction without durable mutation."""
        del source_type, source_ref, metadata, kwargs
        normalized = str(text or "").strip()
        tenant_id = str(tenant_id or "").strip()
        user_id = str(user_id or "").strip()
        if not normalized:
            return {
                "status": "noop",
                "extracted": 0,
                "admitted": 0,
                "persisted": 0,
                "reason": "empty_interaction",
            }
        if not tenant_id or not user_id:
            return {
                "status": "rejected",
                "extracted": 0,
                "admitted": 0,
                "persisted": 0,
                "reason": "missing_tenant_or_user_scope",
            }

        _METRICS["interactions_processed"] += 1
        extraction = await self.signal_pipeline.process_text(
            text=normalized,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        admitted = 0
        for signal in extraction.signals:
            worthiness = await self.worthiness_scorer.evaluate(
                signal.text,
                signal.signal_type,
            )
            if worthiness.get("is_worthy"):
                admitted += 1

        _METRICS["signals_extracted"] += len(extraction.signals)
        _METRICS["signals_admitted"] += admitted
        _METRICS["shadow_mode_runs"] += 1
        return {
            "status": "shadow",
            "extracted": len(extraction.signals),
            "admitted": admitted,
            "persisted": 0,
            "shadow_mode": True,
            "learning_enabled": self.flags.is_enabled(
                "memory_learning_enabled", tenant_id, user_id
            ),
            "errors": list(extraction.errors),
            "processing_time_ms": extraction.processing_time_ms,
        }

    async def close(self) -> None:
        """Canonical manager currently owns no base-level background tasks."""
        return None


def bind_memory_manager(manager: Any) -> None:
    """Bind package-level compatibility calls to the canonical runtime instance."""
    global _memory_manager
    _memory_manager = manager


def _bound_manager() -> Any:
    if _memory_manager is None:
        raise RuntimeError("canonical memory runtime is not bound")
    return _memory_manager


async def update_memory(
    memory_id: str,
    updates: dict[str, Any],
    user_ctx: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Compatibility update API routed through the canonical write authority."""
    content = (
        updates.get("content")
        or updates.get("text")
        or updates.get("query")
        or ""
    )
    if not str(content).strip():
        return {"status": "noop", "memory_id": memory_id, "updated": False}

    context = dict(user_ctx or {})
    tenant_id = str(context.get("tenant_id") or kwargs.get("tenant_id") or "").strip()
    user_id = str(context.get("user_id") or kwargs.get("user_id") or "").strip()
    if not tenant_id or not user_id:
        return {
            "status": "rejected",
            "memory_id": memory_id,
            "updated": False,
            "reason": "missing_tenant_or_user_scope",
        }

    metadata = updates.get("metadata") if isinstance(updates.get("metadata"), dict) else {}
    policy_context = (
        kwargs.get("policy_context")
        or context.get("policy_context")
        or metadata.get("policy_context")
    )
    result = await _bound_manager().process_interaction(
        text=str(content),
        tenant_id=tenant_id,
        user_id=user_id,
        source_type=str(updates.get("source_type") or "manual_update"),
        source_ref=str(updates.get("source_ref") or memory_id),
        metadata=metadata,
        request_id=kwargs.get("request_id") or context.get("request_id"),
        correlation_id=kwargs.get("correlation_id") or context.get("correlation_id"),
        actor_id=kwargs.get("actor_id") or context.get("actor_id"),
        session_id=kwargs.get("session_id") or context.get("session_id"),
        conversation_id=kwargs.get("conversation_id") or context.get("conversation_id"),
        policy_context=policy_context,
    )
    result["memory_id"] = memory_id
    result["updated"] = bool(result.get("persisted"))
    return result


async def export_promoted_artifacts(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Compatibility export routed to the canonical control service."""
    if args:
        raise TypeError("export_promoted_artifacts accepts keyword arguments only")
    service = _bound_manager().control_service
    return await service.export_promoted_artifacts(**kwargs)


def get_metrics() -> dict[str, Any]:
    """Return canonical memory runtime metrics and resilience health."""
    return {
        "memory_runtime": dict(_METRICS),
        "memory_learning_enabled": get_feature_flags().is_enabled(
            "memory_learning_enabled"
        ),
        "resilience_health": get_resilience_health_monitor().get_health_status(),
    }


__all__ = [
    "MemoryRuntimeManager",
    "bind_memory_manager",
    "export_promoted_artifacts",
    "get_metrics",
    "update_memory",
]
