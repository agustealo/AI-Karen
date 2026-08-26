from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING, Self

from .contracts import EventType
from .events import get_observability_emitter

if TYPE_CHECKING:
    from types import TracebackType


class Span:
    """A stage timing span that records a start/completion or failure event.

    Records started_at/completed_at/duration_ms/status so it can later map
    directly to an OpenTelemetry span without changing call sites.
    """

    def __init__(
        self,
        event_type: EventType,
        *,
        status: str | None = None,
        record_on_enter: bool = True,
    ) -> None:
        self.event_type = event_type
        self.emitter = get_observability_emitter()
        self.status = status
        self.started_at: float = 0.0
        self.completed_at: float | None = None
        self.duration_ms: float | None = None
        self.final_status: str | None = None
        self.error_type: str | None = None
        self.error_code: str | None = None
        self.record_on_enter = record_on_enter

    def _start_event(self) -> None:
        self.emitter.emit(self.event_type, status=self.status or "started")

    def _end_event(self, status: str, error_type: str | None = None, error_code: str | None = None) -> None:
        self.final_status = status
        self.emitter.emit(
            self.event_type,
            status=status,
            duration_ms=self.duration_ms,
            error_type=error_type,
            error_code=error_code,
        )

    def __enter__(self) -> Self:
        self.started_at = time.monotonic()
        if self.record_on_enter:
            self._start_event()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.completed_at = time.monotonic()
        self.duration_ms = (self.completed_at - self.started_at) * 1000.0
        if exc_type is not None:
            self._end_event("failed", error_type=exc_type.__name__)
        else:
            self._end_event(self.final_status or self.status or "completed")


@contextmanager
def observe_span(
    event_type: EventType | str,
    *,
    status: str | None = None,
) -> Iterator[Span]:
    """Time an synchronous execution stage and record a completion event."""
    event_type = EventType(event_type) if not isinstance(event_type, EventType) else event_type
    span = Span(event_type, status=status)
    span.started_at = time.monotonic()
    span._start_event()
    try:
        yield span
    except Exception as exc:
        span.completed_at = time.monotonic()
        span.duration_ms = (span.completed_at - span.started_at) * 1000.0
        span._end_event("failed", error_type=type(exc).__name__)
        raise
    else:
        span.completed_at = time.monotonic()
        span.duration_ms = (span.completed_at - span.started_at) * 1000.0
        span._end_event(span.status or "completed")


@asynccontextmanager
async def observe_async_span(
    event_type: EventType | str,
    *,
    status: str | None = None,
) -> AsyncIterator[Span]:
    """Time an asynchronous execution stage and record a completion event."""
    event_type = EventType(event_type) if not isinstance(event_type, EventType) else event_type
    span = Span(event_type, status=status)
    span.started_at = time.monotonic()
    span._start_event()
    try:
        yield span
    except Exception as exc:
        span.completed_at = time.monotonic()
        span.duration_ms = (span.completed_at - span.started_at) * 1000.0
        span._end_event("failed", error_type=type(exc).__name__)
        raise
    else:
        span.completed_at = time.monotonic()
        span.duration_ms = (span.completed_at - span.started_at) * 1000.0
        span._end_event(span.status or "completed")
