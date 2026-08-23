"""Realtime Presence contracts.

Presence is strictly for ephemeral awareness only.
Never stores job status, agent status, workflow truth, permissions, etc.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class PresenceState:
    """Ephemeral presence state."""

    user_id: uuid.UUID
    session_id: uuid.UUID
    status: str = "online"
    view: Optional[str] = None
    device: Optional[str] = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PresenceThrottle:
    """Throttle presence publishes to low-frequency meaningful changes only."""

    def __init__(self, min_interval_seconds: float = 5.0) -> None:
        self._min_interval = min_interval_seconds
        self._last_publish: Dict[uuid.UUID, datetime] = {}

    def should_publish(self, user_id: uuid.UUID, new_state: PresenceState) -> bool:
        last = self._last_publish.get(user_id)
        if last is None:
            self._last_publish[user_id] = new_state.updated_at
            return True
        delta = (new_state.updated_at - last).total_seconds()
        if delta >= self._min_interval:
            self._last_publish[user_id] = new_state.updated_at
            return True
        return False
