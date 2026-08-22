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
    try:
        if get_metrics is None:
            from ai_karen_engine.core.operations.metrics_manager import (
                get_metrics_manager,
            )

            get_metrics = get_metrics_manager

        metrics = get_metrics()

        def _emit(payload: dict[str, Any]) -> None:
            try:
                event_type = payload.get("event_type")
                if not event_type:
                    return
                metrics.increment_counter(
                    "observability_events_total",
                    {"event_type": event_type},
                )
                duration_ms = payload.get("duration_ms")
                if duration_ms is not None:
                    metrics.observe_histogram(
                        "observation_event_duration_ms",
                        float(duration_ms),
                        {"event_type": event_type},
                    )
            except Exception:
                pass

    except Exception:

        def _emit(payload: dict[str, Any]) -> None:  # type: ignore[misc]
            pass

    return ObservabilitySink(name="metrics", emit=_emit, redact=True)
