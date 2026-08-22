from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ai_karen_engine.core.observability.emitter import ObservabilitySink


def create_event_bus_sink(get_bus: Callable[[], Any] | None = None) -> ObservabilitySink:
    """Create a sink that emits observability events to the internal event bus.

    The event bus Event model is enriched with correlation identifiers so
    downstream consumers can correlate events to requests.
    """
    try:
        if get_bus is None:
            from ai_karen_engine.event_bus import get_event_bus
            get_bus = get_event_bus

        bus = get_bus()

        def _emit(payload: dict[str, Any]) -> None:
            try:
                event = bus.Event(
                    event_type=payload.get("event_type", "observability.event"),
                    payload=payload,
                    tenant_id=payload.get("tenant_id"),
                    roles=[],
                )
                bus.publish(event)
            except Exception:
                pass

    except Exception:

        def _emit(payload: dict[str, Any]) -> None:  # type: ignore[misc]
            pass

    return ObservabilitySink(name="event_bus", emit=_emit, redact=True)
