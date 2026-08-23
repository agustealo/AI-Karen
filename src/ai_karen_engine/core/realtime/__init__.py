"""Realtime package marker.

Exports canonical contracts for Supabase realtime integration.
No Supabase SDK imports here.
"""

from ai_karen_engine.core.realtime.connection_state import ConnectionState
from ai_karen_engine.core.realtime.events import (
    EventType,
    EventValidationResult,
    RealtimeEvent,
    is_safe_payload,
    validate_event,
)
from ai_karen_engine.core.realtime.observability import RealtimeMetrics
from ai_karen_engine.core.realtime.presence import PresenceState, PresenceThrottle
from ai_karen_engine.core.realtime.subscriptions import (
    ErrorHandler,
    EventHandler,
    RealtimeSubscriber,
    StateChangeHandler,
    Subscription,
    SubscriptionError,
)
from ai_karen_engine.core.realtime.topics import RealtimeTopicFactory

__all__ = [
    "ConnectionState",
    "EventType",
    "EventValidationResult",
    "RealtimeEvent",
    "RealtimeMetrics",
    "RealtimeSubscriber",
    "RealtimeTopicFactory",
    "Subscription",
    "SubscriptionError",
    "EventHandler",
    "ErrorHandler",
    "StateChangeHandler",
    "PresenceState",
    "PresenceThrottle",
    "is_safe_payload",
    "validate_event",
]
