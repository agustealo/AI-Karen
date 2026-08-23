"""
Realtime publisher accessor for runtime code.

Provides a single importable entrypoint for publishing realtime events
without importing Supabase SDK directly.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ai_karen_engine.integrations.supabase_client import get_supabase_platform
from ai_karen_engine.services.database.repositories.realtime_topic_factory import RealtimeTopicFactory
from ai_karen_engine.services.database.repositories.realtime_event_registry import realtime_events

logger = logging.getLogger(__name__)


def get_realtime_publisher() -> Optional[Any]:
    """Return the configured RealtimePublisher, or None if unavailable."""
    platform = get_supabase_platform()
    return platform.publisher


def is_realtime_available() -> bool:
    """Return True if a realtime publisher is configured."""
    return get_realtime_publisher() is not None


async def publish(topic: str, event: str, payload: Dict[str, Any]) -> None:
    """Publish a realtime event if a publisher is configured."""
    publisher = get_realtime_publisher()
    if publisher is None:
        logger.debug("Realtime publish skipped: publisher not configured")
        return
    await publisher.publish(topic, event, payload)


async def publish_conversation_event(
    tenant_id: str,
    conversation_id: str,
    event_name: str,
    payload: Dict[str, Any],
) -> None:
    """Publish a conversation-scoped realtime event."""
    topic = RealtimeTopicFactory.conversation_topic(tenant_id, conversation_id)
    event = realtime_events.get(event_name, event_name)
    await publish(topic, event, payload)


async def publish_user_event(
    tenant_id: str,
    user_id: str,
    event_name: str,
    payload: Dict[str, Any],
) -> None:
    """Publish a user-scoped realtime event."""
    topic = RealtimeTopicFactory.user_topic(tenant_id, user_id)
    event = realtime_events.get(event_name, event_name)
    await publish(topic, event, payload)


__all__ = [
    "get_realtime_publisher",
    "is_realtime_available",
    "publish",
    "publish_conversation_event",
    "publish_user_event",
]
