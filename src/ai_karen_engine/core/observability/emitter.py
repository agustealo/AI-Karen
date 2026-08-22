from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ai_karen_engine.core.observability.context import get_observability_context
from ai_karen_engine.core.observability.contracts import RuntimeEvent, RuntimeEventType
from ai_karen_engine.core.observability.redaction import RedactionError, redact_data


@dataclass(slots=True)
class ObservabilitySink:
    """A single destination for observability events."""

    name: str
    emit: Callable[[dict[str, Any]], None | Awaitable[None]]
    enabled: bool = True
    redact: bool = True


class ObservabilityEmitter:
    """Single emission path for all runtime observability events.

    Every runtime event must be emitted through this class. It fans out to
    registered sinks and enforces redaction on all payloads.
    """

    def __init__(self) -> None:
        self._sinks: list[ObservabilitySink] = []
        self._default_sink_registered = False

    def register_sink(self, sink: ObservabilitySink) -> None:
        """Register a new event sink."""
        self._sinks.append(sink)

    def ensure_default_sink(self) -> None:
        """Register the default structured-log sink if none exists yet."""
        if self._default_sink_registered:
            return
        self._default_sink_registered = True
        try:
            from ai_karen_engine.core.logging.logger import get_logger

            logger = get_logger(__name__)

            def _log_sink(payload: dict[str, Any]) -> None:
                logger.info("observability.event", extra=payload)

            self.register_sink(
                ObservabilitySink(name="structured_log", emit=_log_sink, redact=True)
            )
        except Exception:
            pass

    def emit(
        self,
        event_type: RuntimeEventType,
        *,
        event_id: str | None = None,
        status: str | None = None,
        error_type: str | None = None,
        error_code: str | None = None,
        duration_ms: float | None = None,
        provider: str | None = None,
        model: str | None = None,
        runtime_engine: str | None = None,
        fallback_level: int | None = None,
        degraded_mode: bool | None = None,
        response_source: str | None = None,
        policy_decision_id: str | None = None,
        prompt_id: str | None = None,
        prompt_version: str | None = None,
        memory_recall_count: int | None = None,
        plugin_id: str | None = None,
        plugin_version: str | None = None,
        intent: str | None = None,
        metadata: dict[str, Any] | None = None,
        **extra: Any,
    ) -> RuntimeEvent:
        """Create and emit a runtime event through all registered sinks.

        Returns the emitted RuntimeEvent so callers can attach it to errors
        or return it in API responses if needed.
        """
        ctx = get_observability_context()
        event = RuntimeEvent(
            event_id=event_id or f"evt_{uuid.uuid4().hex}",
            event_type=event_type,
            timestamp=datetime.utcnow(),
            correlation_id=ctx.correlation_id,
            request_id=ctx.request_id,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            session_id=ctx.session_id,
            conversation_id=ctx.conversation_id,
            status=status,
            error_type=error_type,
            error_code=error_code,
            duration_ms=duration_ms,
            provider=provider,
            model=model,
            runtime_engine=runtime_engine,
            fallback_level=fallback_level,
            degraded_mode=degraded_mode,
            response_source=response_source,
            policy_decision_id=policy_decision_id,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            memory_recall_count=memory_recall_count,
            plugin_id=plugin_id,
            plugin_version=plugin_version,
            intent=intent,
            metadata={**(metadata or {}), **extra},
        )
        payload = self._safe_payload(event)
        for sink in self._sinks:
            if not sink.enabled:
                continue
            try:
                if sink.redact:
                    payload = redact_data(payload)
                result = sink.emit(payload)
                if hasattr(result, "__await__"):
                    # fire-and-forget async sink; do not block the caller
                    pass
            except RedactionError:
                raise
            except Exception:
                continue
        return event

    def _safe_payload(self, event: RuntimeEvent) -> dict[str, Any]:
        try:
            return event.to_dict()
        except Exception:
            return {
                "event_id": getattr(event, "event_id", "unknown"),
                "event_type": getattr(event, "event_type", "unknown"),
            }


_emitter: ObservabilityEmitter | None = None


def get_observability_emitter() -> ObservabilityEmitter:
    """Return the global observability emitter singleton."""
    global _emitter
    if _emitter is None:
        _emitter = ObservabilityEmitter()
        _emitter.ensure_default_sink()
    return _emitter


def emit(
    event_type: RuntimeEventType,
    **kwargs: Any,
) -> RuntimeEvent:
    """Convenience function to emit a runtime event."""
    return get_observability_emitter().emit(event_type, **kwargs)
