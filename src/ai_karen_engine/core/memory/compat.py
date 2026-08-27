"""Compatibility facade for retired package-level memory helpers.

These functions preserve public call shapes while routing all execution into the
canonical runtime and MemoryControlService. No persistence, recall, routing, or
feature-flag authority lives here.
"""

from __future__ import annotations

from typing import Any

from .telemetry import get_memory_metrics


def _manager() -> Any:
    from .memory_runtime_manager import get_memory_manager

    return get_memory_manager()


async def update_memory(
    memory_id: str,
    updates: dict[str, Any],
    user_ctx: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Route the legacy update call through canonical runtime formation."""
    content = updates.get("content") or updates.get("text") or updates.get("query") or ""
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
    result = await _manager().process_interaction(
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
    """Route compatibility export to MemoryControlService."""
    if args:
        raise TypeError("export_promoted_artifacts accepts keyword arguments only")
    return await _manager().control_service.export_promoted_artifacts(**kwargs)


def get_metrics() -> dict[str, Any]:
    return get_memory_metrics()


__all__ = ["export_promoted_artifacts", "get_metrics", "update_memory"]
