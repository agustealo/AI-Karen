"""Write-side base for the canonical memory runtime.

The mature compatibility implementation remains quarantined in
`_legacy_memory_runtime_impl` while inspection/retention surfaces are extracted.
Production recall belongs to NeuroRecall and durable writes are dispatched to
the bound canonical MemoryRuntimeManager.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from . import _legacy_memory_runtime_impl as _legacy

_METRICS = _legacy._METRICS


class MemoryRuntimeManager(_legacy.MemoryRuntimeManager):
    """Compatibility base with recall explicitly disabled."""

    def __init__(self, consolidation_adapter: Any | None = None) -> None:
        super().__init__(
            retrieval_adapter=None,
            consolidation_adapter=consolidation_adapter,
            recall_service=None,
        )
        self._retrieval_adapter = None
        self._recall_service = None

    def set_recall_service(self, service: Any) -> None:
        del service
        raise RuntimeError("write runtime base cannot own recall; use NeuroRecall")

    def set_retrieval_adapter(self, adapter: Any) -> None:
        del adapter
        raise RuntimeError("write runtime base cannot own retrieval; use NeuroRecall")

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
        raise RuntimeError("write runtime base cannot recall; use canonical NeuroRecall")


def bind_memory_manager(manager: Any) -> None:
    """Bind compatibility calls to the canonical runtime instance."""
    _legacy.memory_manager = manager


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

    result = await _legacy.memory_manager.process_interaction(
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
        conversation_id=(
            kwargs.get("conversation_id") or context.get("conversation_id")
        ),
        policy_context=policy_context,
    )
    result["memory_id"] = memory_id
    result["updated"] = bool(result.get("persisted"))
    return result


async def export_promoted_artifacts(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return await _legacy.export_promoted_artifacts(*args, **kwargs)


def get_metrics() -> dict[str, Any]:
    return _legacy.get_metrics()


__all__ = [
    "MemoryRuntimeManager",
    "bind_memory_manager",
    "export_promoted_artifacts",
    "get_metrics",
    "update_memory",
]
