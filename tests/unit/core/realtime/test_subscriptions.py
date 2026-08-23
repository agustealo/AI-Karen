"""Subscription contract tests."""

from __future__ import annotations

import uuid
import pytest

from ai_karen_engine.core.realtime.subscriptions import RealtimeSubscriber, SubscriptionError
from ai_karen_engine.core.realtime.topics import RealtimeTopicFactory
from ai_karen_engine.core.realtime.events import RealtimeEvent, EventType


def test_subscribe_valid_topic():
    factory = RealtimeTopicFactory(tenant_id=str(uuid.uuid4()))
    subscriber = RealtimeSubscriber(factory)
    topic = factory.conversation_topic(str(uuid.uuid4()))
    sub = subscriber.subscribe(topic, lambda e: None)
    assert sub.topic == topic


def test_subscribe_invalid_topic():
    factory = RealtimeTopicFactory(tenant_id=str(uuid.uuid4()))
    subscriber = RealtimeSubscriber(factory)
    with pytest.raises(SubscriptionError):
        subscriber.subscribe("bad-topic", lambda e: None)


def test_handle_message_invalid_event():
    factory = RealtimeTopicFactory(tenant_id=str(uuid.uuid4()))
    subscriber = RealtimeSubscriber(factory)
    sub = subscriber.subscribe(factory.conversation_topic(str(uuid.uuid4())), lambda e: None)
    subscriber.handle_message(sub.subscription_id, {"bad": "data"})


def test_handle_message_valid_event():
    factory = RealtimeTopicFactory(tenant_id=str(uuid.uuid4()))
    received = []
    subscriber = RealtimeSubscriber(factory)
    conv_id = str(uuid.uuid4())
    sub = subscriber.subscribe(factory.conversation_topic(conv_id), lambda e: received.append(e))
    event = RealtimeEvent(
        event_type=EventType.CONVERSATION_MESSAGE_CREATED.value,
        tenant_id=uuid.UUID(factory.tenant_id),
        resource_id=uuid.UUID(conv_id),
    )
    subscriber.handle_message(sub.subscription_id, {
        "event_id": str(event.event_id),
        "event_type": event.event_type,
        "version": event.version,
        "tenant_id": str(event.tenant_id),
        "resource_id": str(event.resource_id),
        "correlation_id": str(event.correlation_id),
        "occurred_at": event.occurred_at.isoformat(),
        "payload": {},
    })
    assert len(received) == 1
    assert received[0].event_type == EventType.CONVERSATION_MESSAGE_CREATED.value
