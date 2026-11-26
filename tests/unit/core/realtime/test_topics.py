"""Realtime topic registry tests."""

from __future__ import annotations

import uuid
import pytest

from ai_karen_engine.core.realtime.topics import RealtimeTopicFactory, _validate_uuid


def test_user_topic_format():
    factory = RealtimeTopicFactory(tenant_id=str(uuid.uuid4()))
    topic = factory.user_topic(str(uuid.uuid4()))
    assert topic.startswith("tenant:")
    assert ":user:" in topic


def test_invalid_tenant_id():
    with pytest.raises(ValueError):
        RealtimeTopicFactory(tenant_id="not-a-uuid")


def test_resolve_valid_topic():
    factory = RealtimeTopicFactory(tenant_id=str(uuid.uuid4()))
    topic = factory.conversation_topic(str(uuid.uuid4()))
    assert factory.resolve_topic(topic) == topic


def test_resolve_invalid_topic():
    factory = RealtimeTopicFactory(tenant_id=str(uuid.uuid4()))
    assert factory.resolve_topic("bad") is None
    assert factory.resolve_topic("tenant:bad:kind:id") is None


def test_resolve_rejects_foreign_tenant_and_extra_segments():
    factory = RealtimeTopicFactory(tenant_id=str(uuid.uuid4()))
    foreign = RealtimeTopicFactory(tenant_id=str(uuid.uuid4()))
    assert factory.resolve_topic(foreign.user_topic(str(uuid.uuid4()))) is None
    assert factory.resolve_topic(foreign.admin_topic()) is None
    assert factory.resolve_topic(factory.admin_topic() + ":extra") is None
    assert factory.resolve_topic(factory.tenant_notifications_topic() + ":extra") is None


def test_resolve_normalizes_uuid_case_and_rejects_newline():
    factory = RealtimeTopicFactory(tenant_id=str(uuid.uuid4()))
    topic = factory.user_topic(str(uuid.uuid4()))
    parts = topic.split(":")
    upper = ":".join((parts[0], parts[1].upper(), parts[2], parts[3].upper()))
    assert factory.resolve_topic(upper) == topic
    assert factory.resolve_topic(topic + "\n") is None
