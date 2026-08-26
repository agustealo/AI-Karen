from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping

from .contracts import ExecutionEvent


class EventSink(ABC):
    """Port for a destination that receives canonical execution events."""

    @abstractmethod
    def emit_event(self, event: ExecutionEvent) -> None: ...


class MetricSink(ABC):
    """Port for a destination that receives aggregated metric samples."""

    @abstractmethod
    def emit_metric(
        self,
        name: str,
        value: float,
        metric_type: str,
        labels: Mapping[str, str],
    ) -> None: ...


class TraceSink(ABC):
    """Port for a destination that receives stage timing/span records."""

    @abstractmethod
    def emit_span(
        self,
        name: str,
        duration_ms: float,
        status: str,
        labels: Mapping[str, str],
    ) -> None: ...


class NullEventSink(EventSink):
    """Default sink used when no OTel backend is configured."""

    def emit_event(self, event: ExecutionEvent) -> None:
        return None


class NullMetricSink(MetricSink):
    def emit_metric(
        self,
        name: str,
        value: float,
        metric_type: str,
        labels: Mapping[str, str],
    ) -> None:
        return None


class NullTraceSink(TraceSink):
    def emit_span(
        self,
        name: str,
        duration_ms: float,
        status: str,
        labels: Mapping[str, str],
    ) -> None:
        return None


class OpenTelemetryEventSink(EventSink):
    """Optional OpenTelemetry adapter.

    Imports opentelemetry lazily so the runtime never depends on it being
    installed. Falls back to a no-op when the SDK is unavailable.
    """

    def __init__(self) -> None:
        self._initialized = False
        self._provider: Callable[[ExecutionEvent], None] | None = None

    def emit_event(self, event: ExecutionEvent) -> None:
        self._ensure_initialized()
        if self._provider is None:
            return
        try:
            self._provider(event)
        except Exception:  # noqa: BLE001 - optional OTel backend must never break emission
            return

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        try:
            from opentelemetry import trace

            provider = trace.get_tracer_provider()

            def _record(evt: ExecutionEvent) -> None:
                tracer = provider.get_tracer("platform.observability")
                with tracer.start_as_current_span(evt.event_type.value) as span:
                    for key, value in evt.to_dict().items():
                        if isinstance(value, (str, int, float, bool)):
                            span.set_attribute(key, value)

            self._provider = _record
        except Exception:  # noqa: BLE001 - OTel may be absent; fall back to a no-op sink
            self._provider = None
