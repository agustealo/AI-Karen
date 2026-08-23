"""
Realtime event registry.

Versioned event definitions so backend and frontend share
a single source of truth for event contracts.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class RealtimeEventRegistry:
    """Registry of versioned realtime events."""

    def __init__(self) -> None:
        self._events: Dict[str, str] = {}

    def register(self, name: str, version: int = 1) -> str:
        key = f"{name}.v{version}"
        self._events[key] = key
        logger.debug("Registered realtime event: %s", key)
        return key

    def get(self, name: str, version: int = 1) -> Optional[str]:
        return self._events.get(f"{name}.v{version}")

    def all_events(self) -> List[str]:
        return list(self._events.keys())


# Canonical event definitions
realtime_events = RealtimeEventRegistry()

realtime_events.register("conversation.message.created")
realtime_events.register("conversation.updated")
realtime_events.register("execution.started")
realtime_events.register("execution.completed")
realtime_events.register("execution.failed")
realtime_events.register("artifact.available")
realtime_events.register("artifact.failed")
realtime_events.register("notification.created")
realtime_events.register("provider.degraded")
realtime_events.register("provider.recovered")

__all__ = [
    "RealtimeEventRegistry",
    "realtime_events",
]
