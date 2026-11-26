"""Realtime subscription interfaces.

Defines the subscription contract consumed by backend and UI.
No Supabase SDK imports here.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from ai_karen_engine.core.realtime.events import RealtimeEvent, validate_event
from ai_karen_engine.core.realtime.topics import RealtimeTopicFactory
from ai_karen_engine.core.realtime.connection_state import ConnectionState


logger = logging.getLogger(__name__)


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
# None is admission; an event is a fresh delivery authorization request.
# The trusted runtime supplies the policy, not the topic or event payload.
SubscriptionAuthorizer = Callable[[str, Optional[RealtimeEvent]], bool]


class RealtimeSubscriber:
    """Subscription management interface.

    Backend implementation will wire to Supabase Broadcast.
    Frontend implementation will consume via hooks.
    """

    def __init__(
        self,
        topic_factory: RealtimeTopicFactory,
        *,
        authorize: Optional[SubscriptionAuthorizer] = None,
    ) -> None:
        self._topic_factory = topic_factory
        self._authorize = authorize
        self._subscriptions: Dict[str, Subscription] = {}
        self._event_handlers: Dict[str, List[EventHandler]] = {}
        self._error_handlers: Dict[str, ErrorHandler] = {}
        self._state_handlers: List[StateChangeHandler] = []

    def subscribe(
        self,
        topic: str,
        on_event: EventHandler,
        on_error: Optional[ErrorHandler] = None,
    ) -> Subscription:
        validated = self._topic_factory.resolve_topic(topic)
        if validated is None:
            raise SubscriptionError("Invalid realtime topic")
        if not self._is_authorized(validated, None):
            raise SubscriptionError("Realtime subscription not authorized")

        sub_id = f"sub-{uuid.uuid4()}"
        subscription = Subscription(subscription_id=sub_id, topic=validated)
        self._subscriptions[sub_id] = subscription
        self._event_handlers.setdefault(sub_id, []).append(on_event)
        if on_error:
            self._error_handlers[sub_id] = on_error
        return subscription

    def unsubscribe(self, subscription_id: str) -> None:
        self._subscriptions.pop(subscription_id, None)
        self._event_handlers.pop(subscription_id, None)
        self._error_handlers.pop(subscription_id, None)

    def handle_message(self, sub_id: str, raw: Dict[str, Any]) -> None:
        subscription = self._subscriptions.get(sub_id)
        if subscription is None:
            return
        result = validate_event(raw)
        if not result.valid or result.event is None:
            self._notify_error(sub_id, SubscriptionError("Invalid realtime event"))
            return
        event = result.event
        # Canonical topic syntax and tenant membership are necessary, not sufficient.
        if event.tenant_id != uuid.UUID(self._topic_factory.tenant_id):
            return
        if not self._is_authorized(subscription.topic, event):
            return
        # Authorization may revoke/unsubscribe during the policy call.
        if self._subscriptions.get(sub_id) is not subscription:
            return
        for handler in self._event_handlers.get(sub_id, []):
            handler(event)

    def _is_authorized(self, topic: str, event: Optional[RealtimeEvent]) -> bool:
        if self._authorize is None:
            return False
        try:
            # Do not accept truthy non-boolean results or accidental async policies.
            return self._authorize(topic, event) is True
        except Exception:
            logger.warning("Realtime authorization failed; access denied")
            return False

    def _notify_error(self, sub_id: str, exc: Exception) -> None:
        handler = self._error_handlers.get(sub_id)
        if handler is not None:
            handler(exc)

    @property
    def active_subscriptions(self) -> List[Subscription]:
        return list(self._subscriptions.values())

    def on_state_change(self, handler: StateChangeHandler) -> None:
        self._state_handlers.append(handler)
