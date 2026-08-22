from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ai_karen_engine.core.observability.emitter import ObservabilitySink


def create_metrics_sink(get_metrics: Callable[[], Any] | None = None) -> ObservabilitySink:
    """Create a sink that records select observability events as metrics.

    This is intentionally narrow: it only records counts/latencies for
    event types that are already safe to aggregate. It does not attempt
    to export arbitrary metadata as labels.
    """
    _event_counter = None
    _duration_histogram = None

    def _ensure_metrics(manager):
        nonlocal _event_counter, _duration_histogram
        if _event_counter is None:
            _event_counter = manager.register_counter(
                "observability_events_total",
                "Total observability events emitted",
                ["event_type"],
            )
        if _duration_histogram is None:
            _duration_histogram = manager.register_histogram(
                "observation_event_duration_ms",
                "Observability event processing duration in milliseconds",
                ["event_type"],
            )

    try:
        if get_metrics is None:
            from ai_karen_engine.core.observability.metrics import (
                get_metrics_manager,
            )

            get_metrics = get_metrics_manager

        manager = get_metrics()
        _ensure_metrics(manager)

        def _emit(payload: dict[str, Any]) -> None:
            try:
                event_type = payload.get("event_type")
                if not event_type:
                    return
                if _event_counter is not None:
                    _event_counter.labels(event_type=event_type).inc()
                duration_ms = payload.get("duration_ms")
                if duration_ms is not None and _duration_histogram is not None:
                    _duration_histogram.labels(event_type=event_type).observe(
                        float(duration_ms)
                    )
            except Exception:
                pass

    except Exception:

        def _emit(payload: dict[str, Any]) -> None:  # type: ignore[misc]
            pass

    return ObservabilitySink(name="metrics", emit=_emit, redact=True)
