from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

from .context import get_correlation_context
from .contracts import ErrorCategory, EventType, ExecutionEvent
from .redaction import redact_data

logger = logging.getLogger("ai_karen_engine.platform.observability")


@runtime_checkable
class ObservabilitySink(Protocol):
    """Destination for canonical execution events.

    Implementations receive the live event and decide how to serialize it.
    Sinks that persist or log output MUST redact before writing.
    """

    name: str

    def emit(self, event: ExecutionEvent) -> None: ...


class StructuredLoggingSink:
    """Local-first default sink: writes events as structured JSON log records.

    Applies central redaction before logging. Contains no external telemetry
    dependency.
    """

    name = "structured_log"

    def __init__(self, sink_logger: logging.Logger | None = None) -> None:
        self._logger = sink_logger or logger

    def emit(self, event: ExecutionEvent) -> None:
        payload = redact_data(event.to_dict())
        self._logger.info("observability.event", extra={"observability_event": payload})


class InMemorySink:
    """Captures events in a list; for tests and diagnostics."""

    name = "memory"

    def __init__(self) -> None:
        self.events: list[ExecutionEvent] = []

    def emit(self, event: ExecutionEvent) -> None:
        self.events.append(event)


class ObservabilityEmitter:
    """Single emission path for all platform observability events.

    Every event is bound to the current correlation context, then fanned out to
    registered sinks. Sink failures never crash the request path.
    """

    def __init__(self, sinks: Iterable[ObservabilitySink] | None = None) -> None:
        self._sinks: list[ObservabilitySink] = list(sinks) if sinks else []

    def register_sink(self, sink: ObservabilitySink) -> None:
        self._sinks.append(sink)

    def emit(
        self,
        event_type: EventType,
        *,
        event_id: str | None = None,
        status: str | None = None,
        error_category: ErrorCategory | None = None,
        error_type: str | None = None,
        error_code: str | None = None,
        retryable: bool | None = None,
        duration_ms: float | None = None,
        provider: str | None = None,
        model: str | None = None,
        runtime_engine: str | None = None,
        fallback_level: int | None = None,
        response_source: str | None = None,
        degraded_mode: bool | None = None,
        execution_layer: str | None = None,
        requested_target: str | None = None,
        resolved_target: str | None = None,
        degradation_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        **fields: Any,
    ) -> ExecutionEvent:
        ctx = get_correlation_context()
        event = ExecutionEvent(
            event_id=event_id or f"evt_{uuid.uuid4().hex}",
            event_type=event_type,
            request_id=ctx.request_id,
            correlation_id=ctx.correlation_id,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            session_id=ctx.session_id,
            conversation_id=ctx.conversation_id,
            status=status,
            error_category=error_category,
            error_type=error_type,
            error_code=error_code,
            retryable=retryable,
            duration_ms=duration_ms,
            provider=provider,
            model=model,
            runtime_engine=runtime_engine,
            fallback_level=fallback_level,
            response_source=response_source,
            degraded_mode=degraded_mode,
            execution_layer=execution_layer,
            requested_target=requested_target,
            resolved_target=resolved_target,
            degradation_type=degradation_type,
            metadata={**(metadata or {}), **fields},
        )
        self._dispatch(event)
        return event

    def _dispatch(self, event: ExecutionEvent) -> None:
        for sink in self._sinks:
            try:
                sink.emit(event)
            except Exception:  # noqa: BLE001, S112 - a failing sink must never crash the request path
                continue


_emitter: ObservabilityEmitter | None = None


def get_observability_emitter() -> ObservabilityEmitter:
    """Return the process-wide observability emitter singleton."""
    global _emitter
    if _emitter is None:
        _emitter = ObservabilityEmitter([StructuredLoggingSink()])
    return _emitter


def emit_event(event_type: EventType, **fields: Any) -> ExecutionEvent:
    """Convenience function to emit a canonical event."""
    return get_observability_emitter().emit(event_type, **fields)
