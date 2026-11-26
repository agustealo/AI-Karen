"""Regression proof for the existing legacy work queue, not private push."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, Mock

import fakeredis
import pytest
from redis.exceptions import WatchError

from ai_karen_engine.event_bus import EventBus, EventBusUnavailable, RedisEventBus


@pytest.fixture(params=["memory", "redis"])
def bus(request):
    if request.param == "memory":
        return EventBus(use_redis=False)
    return RedisEventBus(redis_client=fakeredis.FakeRedis(), list_key="isolated-events")


def publish(bus, tenant, role="user"):
    return bus.publish("test", "event", {"value": tenant}, roles=[role], tenant_id=tenant)


def test_retains_foreign_role_and_unattributed_events(bus):
    a = publish(bus, "tenant-a")
    b = publish(bus, "tenant-b")
    admin = publish(bus, "tenant-a", "admin")
    publish(bus, None, "admin")
    assert [e.id for e in bus.consume(["user"], "tenant-a")] == [a]
    assert [e.id for e in bus.consume(["user"], "tenant-b")] == [b]
    assert [e.id for e in bus.consume(["admin"], "tenant-a")] == [admin]
    assert bus.consume(["admin"], "tenant-a") == []
    with pytest.raises(PermissionError):
        bus.consume(["admin"], None)


@pytest.mark.parametrize("roles,tenant", [
    (None, "tenant-a"), ([], "tenant-a"), ("admin", "tenant-a"),
    (["user"], ""), (["user"], None), (["user"], " tenant-a "),
])
def test_scope_denied_without_destructive_read(bus, roles, tenant):
    eid = publish(bus, "tenant-a")
    with pytest.raises(PermissionError):
        bus.consume(roles, tenant)
    assert [e.id for e in bus.consume(["user"], "tenant-a")] == [eid]


def test_explicit_redis_queue_key_and_malformed_entry_preserved():
    client = fakeredis.FakeRedis()
    one = RedisEventBus(redis_client=client, list_key="one")
    two = RedisEventBus(redis_client=client, list_key="two")
    a, b = publish(one, "tenant-a"), publish(two, "tenant-a")
    client.rpush("one", b"malformed")
    assert [e.id for e in one.consume(["user"], "tenant-a")] == [a]
    assert client.lrange("one", 0, -1) == [b"malformed"]
    assert [e.id for e in two.consume(["user"], "tenant-a")] == [b]


def test_concurrent_consumers_do_not_duplicate_or_lose_events(bus):
    expected = {publish(bus, "tenant-a") for _ in range(12)}
    foreign = publish(bus, "tenant-b")

    def consume():
        try:
            return bus.consume(["user"], "tenant-a")
        except EventBusUnavailable:
            # Bounded WATCH contention is explicit; a later attempt can reconcile.
            return []

    with ThreadPoolExecutor(max_workers=2) as pool:
        batches = list(pool.map(lambda _: consume(), range(2)))
    received = [e.id for batch in batches for e in batch]
    received.extend(e.id for e in bus.consume(["user"], "tenant-a"))
    assert len(received) == len(expected)
    assert set(received) == expected
    assert [e.id for e in bus.consume(["user"], "tenant-b")] == [foreign]


def test_redis_outage_does_not_switch_to_memory():
    client = Mock()
    client.rpush.side_effect = TimeoutError("private connection detail")
    client.pipeline.side_effect = TimeoutError("private connection detail")
    bus = RedisEventBus(redis_client=client)
    hook = Mock()
    bus.register_hook_handler("*", hook)
    with pytest.raises(EventBusUnavailable, match="publication unavailable"):
        publish(bus, "tenant-a")
    hook.assert_not_called()
    with pytest.raises(EventBusUnavailable, match="consumption unavailable"):
        bus.consume(["user"], "tenant-a")
    assert bus._redis is client
    assert not bus._queue


def test_watch_conflict_is_bounded_and_not_reported_as_success():
    client = Mock()
    client.pipeline.return_value = MagicMock()
    pipe = client.pipeline.return_value.__enter__.return_value
    pipe.watch.side_effect = WatchError()
    bus = RedisEventBus(redis_client=client)
    with pytest.raises(EventBusUnavailable, match="changed during consumption"):
        bus.consume(["user"], "tenant-a")
    assert pipe.watch.call_count == 3
    pipe.execute.assert_not_called()


@pytest.mark.asyncio
async def test_route_preserves_scope_and_reports_unavailability(monkeypatch):
    from fastapi import HTTPException, Response
    from ai_karen_engine.api_routes.system import events as route

    fake = Mock()
    monkeypatch.setattr(route, "get_event_bus", lambda: fake)
    fake.consume.side_effect = EventBusUnavailable("internal")
    with pytest.raises(HTTPException) as error:
        await route.consume_events(Response(), {"roles": ["user"]}, "tenant-a")
    assert error.value.status_code == 503
    assert error.value.headers["Cache-Control"] == "no-store"
    fake.consume.assert_called_once_with(["user"], tenant_id="tenant-a")
