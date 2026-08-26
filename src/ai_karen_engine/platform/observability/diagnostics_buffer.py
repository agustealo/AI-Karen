from __future__ import annotations

import threading
from collections import deque
from typing import Any

from .contracts import ExecutionEvent
from .redaction import redact_data


class BoundedDiagnosticsBuffer:
    """Thread-safe ring buffer holding the most recent sanitized events.

    This is an operational buffer only: it is never a durable store or audit
    authority. All fields are redacted on entry. It powers beta diagnostics
    without a heavyweight backend.
    """

    def __init__(self, capacity: int = 500) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._capacity = capacity
        self._lock = threading.Lock()
        self._events: deque[dict[str, Any]] = deque(maxlen=capacity)

    @property
    def capacity(self) -> int:
        return self._capacity

    def add(self, event: ExecutionEvent) -> None:
        record = redact_data(event.to_dict())
        record["_seq"] = len(self._events)
        with self._lock:
            self._events.append(record)

    def add_payload(self, payload: dict[str, Any]) -> None:
        record = redact_data(payload)
        with self._lock:
            record["_seq"] = len(self._events)
            self._events.append(record)

    def recent(self, count: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            events = list(self._events)
        if count is None:
            return events
        return events[-count:]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)


_buffer: BoundedDiagnosticsBuffer | None = None


def get_diagnostics_buffer() -> BoundedDiagnosticsBuffer:
    """Return the process-wide diagnostics buffer singleton (default 500)."""
    global _buffer
    if _buffer is None:
        _buffer = BoundedDiagnosticsBuffer()
    return _buffer
