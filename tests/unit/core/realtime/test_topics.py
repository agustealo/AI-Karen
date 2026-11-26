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


def test_legacy_factory_delegates_every_topic_kind():
    from ai_karen_engine.services.database.repositories.realtime_topic_factory import (
        RealtimeTopicFactory as LegacyFactory,
    )

    tenant = str(uuid.uuid4())
    resource = str(uuid.uuid4())
    canonical = RealtimeTopicFactory(tenant)
    for kind in ("user_topic", "conversation_topic", "execution_topic"):
        actual = getattr(LegacyFactory, kind)(tenant.upper(), resource.upper())
        assert actual == getattr(canonical, kind)(resource)
        assert LegacyFactory.is_private(actual)
    assert LegacyFactory.admin_topic(tenant.upper()) == canonical.admin_topic()
    assert LegacyFactory.is_private(canonical.tenant_notifications_topic())


def test_legacy_factory_no_longer_accepts_arbitrary_identifiers():
    from ai_karen_engine.services.database.repositories.realtime_topic_factory import (
        RealtimeTopicFactory as LegacyFactory,
    )

    tenant = str(uuid.uuid4())
    resource = str(uuid.uuid4())
    with pytest.raises(ValueError):
        LegacyFactory.user_topic("tenant-name", resource)
    with pytest.raises(ValueError):
        LegacyFactory.user_topic(tenant, "user-name")
    for topic in (
        "tenant:t1:user:u1",
        f"tenant:{tenant}:admin:extra",
        f"tenant:{tenant}:user:{resource}:extra",
        f"tenant:{tenant}:user:{resource}\n",
        f"tenant:{tenant}:unknown",
        f"public:{tenant}:user:{resource}",
    ):
        assert not LegacyFactory.is_private(topic)
