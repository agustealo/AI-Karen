"""Realtime subscription interfaces.

Defines the subscription contract consumed by backend and UI.
No Supabase SDK imports here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from ai_karen_engine.core.realtime.events import EventValidationResult, RealtimeEvent, validate_event
from ai_karen_engine.core.realtime.topics import RealtimeTopicFactory
from ai_karen_engine.core.realtime.connection_state import ConnectionState


class SubscriptionError(Exception):
    pass


@dataclass(frozen=True)
class Subscription:
    """Represents an active realtime subscription."""

    subscription_id: str
    topic: str
    state: ConnectionState = ConnectionState.CONNECTING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


EventHandler = Callable[[RealtimeEvent], None]
ErrorHandler = Callable[[Exception], None]
StateChangeHandler = Callable[[ConnectionState, ConnectionState], None]


class RealtimeSubscriber:
    """Subscription management interface.

    Backend implementation will wire to Supabase Broadcast.
    Frontend implementation will consume via hooks.
    """

    def __init__(self, topic_factory: RealtimeTopicFactory) -> None:
        self._topic_factory = topic_factory
        self._subscriptions: Dict[str, Subscription] = {}
        self._event_handlers: Dict[str, List[EventHandler]] = {}
        self._error_handlers: List[ErrorHandler] = []
        self._state_handlers: List[StateChangeHandler] = []

    def subscribe(
        self,
        topic: str,
        on_event: EventHandler,
        on_error: Optional[ErrorHandler] = None,
    ) -> Subscription:
        validated = self._topic_factory.resolve_topic(topic)
        if validated is None:
            raise SubscriptionError(f"Invalid topic: {topic!r}")

        sub_id = f"sub-{uuid.uuid4()}"
        subscription = Subscription(subscription_id=sub_id, topic=validated)
        self._subscriptions[sub_id] = subscription
        self._event_handlers.setdefault(sub_id, []).append(on_event)
        if on_error:
            self._error_handlers.append(on_error)
        return subscription

    def unsubscribe(self, subscription_id: str) -> None:
        self._subscriptions.pop(subscription_id, None)
        self._event_handlers.pop(subscription_id, None)

    def handle_message(self, sub_id: str, raw: Dict[str, Any]) -> None:
        result = validate_event(raw)
        if not result.valid or result.event is None:
            self._notify_error(SubscriptionError(f"Invalid event: {result.reason}"))
            return
        if not self._is_authorized(result.event):
            return
        for handler in self._event_handlers.get(sub_id, []):
            handler(result.event)

    def _is_authorized(self, event: RealtimeEvent) -> bool:
        return True

    def _notify_error(self, exc: Exception) -> None:
        for handler in self._error_handlers:
            handler(exc)

    @property
    def active_subscriptions(self) -> List[Subscription]:
        return list(self._subscriptions.values())

    def on_state_change(self, handler: StateChangeHandler) -> None:
        self._state_handlers.append(handler)
