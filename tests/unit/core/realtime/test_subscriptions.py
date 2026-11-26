"""Subscription contract tests."""

from __future__ import annotations

import uuid
import pytest

from ai_karen_engine.core.realtime.subscriptions import RealtimeSubscriber, SubscriptionError
from ai_karen_engine.core.realtime.topics import RealtimeTopicFactory
from ai_karen_engine.core.realtime.events import RealtimeEvent, EventType


def _allow_test_policy(topic, event):
    # Tests only: resource binding is supplied by the trusted caller.
    return event is None or topic.endswith(str(event.resource_id))


def test_subscribe_valid_topic():
    factory = RealtimeTopicFactory(tenant_id=str(uuid.uuid4()))
    subscriber = RealtimeSubscriber(factory, authorize=_allow_test_policy)
    topic = factory.conversation_topic(str(uuid.uuid4()))
    sub = subscriber.subscribe(topic, lambda e: None)
    assert sub.topic == topic


def test_subscribe_invalid_topic():
    factory = RealtimeTopicFactory(tenant_id=str(uuid.uuid4()))
    subscriber = RealtimeSubscriber(factory, authorize=_allow_test_policy)
    with pytest.raises(SubscriptionError):
        subscriber.subscribe("bad-topic", lambda e: None)


def test_handle_message_invalid_event():
    factory = RealtimeTopicFactory(tenant_id=str(uuid.uuid4()))
    subscriber = RealtimeSubscriber(factory, authorize=_allow_test_policy)
    sub = subscriber.subscribe(factory.conversation_topic(str(uuid.uuid4())), lambda e: None)
    subscriber.handle_message(sub.subscription_id, {"bad": "data"})


def test_handle_message_valid_event():
    factory = RealtimeTopicFactory(tenant_id=str(uuid.uuid4()))
    received = []
    subscriber = RealtimeSubscriber(factory, authorize=_allow_test_policy)
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


def _raw_event(tenant_id, resource_id):
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": EventType.CONVERSATION_MESSAGE_CREATED.value,
        "tenant_id": str(tenant_id),
        "resource_id": str(resource_id),
        "correlation_id": str(uuid.uuid4()),
    }


def test_missing_or_denied_policy_rejects_admission():
    factory = RealtimeTopicFactory(tenant_id=str(uuid.uuid4()))
    topic = factory.user_topic(str(uuid.uuid4()))
    for subscriber in (
        RealtimeSubscriber(factory),
        RealtimeSubscriber(factory, authorize=lambda topic, event: False),
        RealtimeSubscriber(factory, authorize=lambda topic, event: 1),
    ):
        with pytest.raises(SubscriptionError):
            subscriber.subscribe(topic, lambda event: None)
        assert subscriber.active_subscriptions == []


def test_delivery_requires_fresh_policy_and_matching_tenant():
    factory = RealtimeTopicFactory(tenant_id=str(uuid.uuid4()))
    resource_id = uuid.uuid4()
    allowed = True
    received = []

    def authorize(topic, event):
        return allowed and _allow_test_policy(topic, event)

    subscriber = RealtimeSubscriber(factory, authorize=authorize)
    sub = subscriber.subscribe(factory.conversation_topic(str(resource_id)), received.append)
    subscriber.handle_message(sub.subscription_id, _raw_event(uuid.uuid4(), resource_id))
    subscriber.handle_message(sub.subscription_id, _raw_event(factory.tenant_id, uuid.uuid4()))
    assert received == []
    subscriber.handle_message(sub.subscription_id, _raw_event(factory.tenant_id, resource_id))
    assert len(received) == 1
    allowed = False
    subscriber.handle_message(sub.subscription_id, _raw_event(factory.tenant_id, resource_id))
    assert len(received) == 1


def test_authorization_exception_denies_delivery():
    factory = RealtimeTopicFactory(tenant_id=str(uuid.uuid4()))
    resource_id = uuid.uuid4()

    def authorize(topic, event):
        if event is not None:
            raise RuntimeError("policy unavailable")
        return True

    received = []
    subscriber = RealtimeSubscriber(factory, authorize=authorize)
    sub = subscriber.subscribe(factory.conversation_topic(str(resource_id)), received.append)
    subscriber.handle_message(sub.subscription_id, _raw_event(factory.tenant_id, resource_id))
    assert received == []


def test_errors_are_subscription_scoped_and_removed_on_unsubscribe():
    factory = RealtimeTopicFactory(tenant_id=str(uuid.uuid4()))
    subscriber = RealtimeSubscriber(factory, authorize=_allow_test_policy)
    errors_a, errors_b = [], []
    a = subscriber.subscribe(factory.conversation_topic(str(uuid.uuid4())), lambda e: None, errors_a.append)
    subscriber.subscribe(factory.conversation_topic(str(uuid.uuid4())), lambda e: None, errors_b.append)
    subscriber.handle_message(a.subscription_id, {})
    assert len(errors_a) == 1
    assert errors_b == []
    subscriber.unsubscribe(a.subscription_id)
    subscriber.handle_message(a.subscription_id, {})
    assert len(errors_a) == 1
    assert errors_b == []
