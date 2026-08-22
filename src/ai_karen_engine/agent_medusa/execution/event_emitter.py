"""Structured execution event emitter (AGENT-LIVE-1 A24).

The coordinator emits one AgentEvent per step/tool boundary. Sinks are
pluggable: the default collects in-memory for the trajectory; a stream sink
(e.g. websocket) can be attached for live UI progress. The event schema in
contracts/events.py is the stable contract the UI consumes.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional

from ..contracts.events import AgentEvent

logger = logging.getLogger(__name__)


class EventEmitter:
    """Collects and forwards structured AgentEvents to attached sinks."""

    def __init__(self, sinks: Optional[List[Callable[[AgentEvent], None]]] = None) -> None:
        self._events: List[AgentEvent] = []
        self._sinks: List[Callable[[AgentEvent], None]] = list(sinks or [])

    def attach_sink(self, sink: Callable[[AgentEvent], None]) -> None:
        self._sinks.append(sink)

    async def emit(self, event: AgentEvent) -> None:
        self._events.append(event)
        for sink in self._sinks:
            try:
                sink(event)
            except Exception:  # sink failures must never break execution
                pass

    @property
    def events(self) -> List[AgentEvent]:
        return list(self._events)
