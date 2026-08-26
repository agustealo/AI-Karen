from __future__ import annotations

from typing import Any, Protocol

from .context import get_correlation_context
from .contracts import EventType, ExecutionEvent
from .events import ObservabilityEmitter, get_observability_emitter


class RuntimeMetadataLike(Protocol):
    """Structural type for the runtime envelope metadata.

    Platform observability records these fields without importing the runtime
    that owns them, preserving the runtime envelope as response authority.
    """

    requested_target: str | None
    resolved_target: str | None
    provider: str | None
    model: str | None
    runtime_engine: str | None
    execution_layer: str | None
    response_source: str | None
    fallback_level: int
    degraded_mode: bool
    degradation_type: str | None


def record_runtime_metadata(
    metadata: RuntimeMetadataLike,
    *,
    emitter: ObservabilityEmitter | None = None,
    event_type: EventType = EventType.PROVIDER_SELECTION_COMPLETED,
) -> ExecutionEvent:
    """Map runtime metadata into a canonical observability event.

    The runtime envelope remains the authority for the response; this merely
    records what the runtime decided (target, provider, fallback, degraded).
    """
    emit = emitter or get_observability_emitter()
    return emit.emit(
        event_type,
        requested_target=metadata.requested_target,
        resolved_target=metadata.resolved_target,
        provider=metadata.provider,
        model=metadata.model,
        runtime_engine=metadata.runtime_engine,
        execution_layer=metadata.execution_layer,
        response_source=metadata.response_source,
        fallback_level=metadata.fallback_level or None,
        degraded_mode=metadata.degraded_mode,
        degradation_type=metadata.degradation_type,
        status="degraded" if metadata.degraded_mode else "completed",
    )


def correlation_ids_from_metadata(metadata: RuntimeMetadataLike) -> dict[str, Any]:
    """Pull correlation identities off runtime metadata for context binding."""
    return {
        "request_id": getattr(metadata, "request_id", None),
        "correlation_id": getattr(metadata, "correlation_id", None),
        "tenant_id": getattr(metadata, "tenant_id", None),
        "user_id": getattr(metadata, "user_id", None),
        "session_id": getattr(metadata, "session_id", None),
        "conversation_id": getattr(metadata, "conversation_id", None),
    }


__all__ = [
    "RuntimeMetadataLike",
    "correlation_ids_from_metadata",
    "get_correlation_context",
    "record_runtime_metadata",
]
