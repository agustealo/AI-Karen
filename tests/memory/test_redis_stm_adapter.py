from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ai_karen_engine.core.memory.episodic import EpisodeFrame, EpisodeObservation
from ai_karen_engine.core.memory.stm import STMScope, STMSlot
from ai_karen_engine.platform.memory.redis.stm_adapter import RedisSTMAdapter


class FakeRedisManager:
    prefix = "kari"

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}
        self._degraded = False

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, **_: object) -> bool:
        self.values[key] = value
        self.ttls[key] = ex
        return True

    async def conditional_set(self, key, value, *, ex, should_replace):
        if self._degraded:
            return False
        if should_replace(self.values.get(key)):
            return await self.set(key, value, ex=ex)
        return True

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self.values:
                deleted += 1
                self.values.pop(key, None)
                self.ttls.pop(key, None)
        return deleted

    async def exists(self, *keys: str) -> int:
        return sum(1 for key in keys if key in self.values)

    def is_degraded(self) -> bool:
        return self._degraded


@pytest.mark.asyncio
async def test_slots_are_physically_isolated() -> None:
    redis = FakeRedisManager()
    adapter = RedisSTMAdapter(redis_manager=redis, default_ttl_seconds=600)
    scope = STMScope(tenant_id="tenant-a", user_id="user-a", session_id="session-a")

    await adapter.put_slot(
        scope=scope,
        slot=STMSlot.ACTIVE_GOAL,
        value={"goal_id": "goal-1"},
    )
    await adapter.put_slot(
        scope=scope,
        slot=STMSlot.TOOL_STATE,
        value={"tool": "search", "status": "running"},
    )

    assert await adapter.get_slot(scope=scope, slot=STMSlot.ACTIVE_GOAL) == {
        "goal_id": "goal-1"
    }
    assert await adapter.get_slot(scope=scope, slot=STMSlot.TOOL_STATE) == {
        "tool": "search",
        "status": "running",
    }
    assert len(redis.values) == 2


@pytest.mark.asyncio
async def test_scope_is_part_of_every_physical_key() -> None:
    redis = FakeRedisManager()
    adapter = RedisSTMAdapter(redis_manager=redis, default_ttl_seconds=600)
    a = STMScope(tenant_id="tenant-a", user_id="user", session_id="session")
    b = STMScope(tenant_id="tenant-b", user_id="user", session_id="session")

    await adapter.put_slot(scope=a, slot=STMSlot.WORKING_STATE, value={"value": "a"})
    await adapter.put_slot(scope=b, slot=STMSlot.WORKING_STATE, value={"value": "b"})

    assert await adapter.get_slot(scope=a, slot=STMSlot.WORKING_STATE) == {"value": "a"}
    assert await adapter.get_slot(scope=b, slot=STMSlot.WORKING_STATE) == {"value": "b"}


@pytest.mark.asyncio
async def test_ttl_and_payload_budget_are_enforced() -> None:
    redis = FakeRedisManager()
    adapter = RedisSTMAdapter(
        redis_manager=redis,
        default_ttl_seconds=900,
        max_slot_bytes=1024,
    )
    scope = STMScope(tenant_id="tenant", user_id="user", session_id="session")

    await adapter.put_slot(
        scope=scope,
        slot=STMSlot.RECENT_CONTEXT,
        value={"summary": "small"},
    )
    key = next(iter(redis.values))
    assert redis.ttls[key] == 900

    with pytest.raises(ValueError, match="exceeds configured limit"):
        await adapter.put_slot(
            scope=scope,
            slot=STMSlot.RECENT_CONTEXT,
            value={"summary": "x" * 2048},
        )


@pytest.mark.asyncio
async def test_episode_compatibility_uses_active_episode_slot() -> None:
    redis = FakeRedisManager()
    adapter = RedisSTMAdapter(redis_manager=redis, default_ttl_seconds=600)
    frame = EpisodeFrame.new(
        EpisodeObservation(
            tenant_id="tenant",
            user_id="user",
            session_id="session",
            observed_at=datetime.now(timezone.utc),
            text="continue the current task",
            goal_key="goal-1",
            project_key="project-1",
        )
    )

    assert await adapter.save(frame) is True
    restored = await adapter.load(
        tenant_id="tenant",
        user_id="user",
        session_id="session",
    )

    assert restored is not None
    assert restored.episode_group_id == frame.episode_group_id
    assert restored.goal_key == "goal-1"
    assert restored.project_key == "project-1"

    assert await adapter.clear(
        tenant_id="tenant",
        user_id="user",
        session_id="session",
    ) is True
    assert await adapter.load(
        tenant_id="tenant",
        user_id="user",
        session_id="session",
    ) is None


def test_adapter_reports_degraded_backing() -> None:
    redis = FakeRedisManager()
    redis._degraded = True
    adapter = RedisSTMAdapter(redis_manager=redis, default_ttl_seconds=600)
    assert adapter.degraded() is True


@pytest.mark.asyncio
async def test_ordered_episode_adapter_delegates_atomic_compare_and_validates_scope():
    import json
    from dataclasses import replace
    from datetime import timedelta
    from unittest.mock import AsyncMock

    redis = FakeRedisManager()
    adapter = RedisSTMAdapter(redis_manager=redis, default_ttl_seconds=600)
    scope = STMScope("tenant", "user", "session")
    frame = EpisodeFrame.new(EpisodeObservation(
        tenant_id=scope.tenant_id, user_id=scope.user_id, session_id=scope.session_id,
        observed_at=datetime.now(timezone.utc), text="committed fact",
    ))
    value = {**frame.to_dict(), "event_id": "event-1", "source_type": "chat_user",
             "source_ref": "conversation-1"}

    async def conditional(key, payload, *, ex, should_replace):
        assert ex == 600
        assert should_replace(None)
        assert not should_replace(json.dumps(value))
        assert not should_replace(json.dumps(replace(
            frame, updated_at=frame.updated_at + timedelta(seconds=1),
        ).to_dict()))
        assert should_replace(json.dumps(replace(
            frame, updated_at=frame.updated_at - timedelta(seconds=1),
        ).to_dict()))
        return await redis.set(key, payload, ex=ex)

    redis.conditional_set = AsyncMock(side_effect=conditional)
    assert await adapter.put_episode_if_newer(scope=scope, value=value)
    assert await adapter.get_slot(scope=scope, slot=STMSlot.ACTIVE_EPISODE) == value
    with pytest.raises(ValueError, match="scope mismatch"):
        await adapter.put_episode_if_newer(scope=scope, value={**value, "tenant_id": "foreign"})
    redis.conditional_set.assert_awaited_once()


@pytest.mark.asyncio
async def test_conditional_redis_write_retries_watch_conflict_and_never_uses_local_fallback():
    from unittest.mock import AsyncMock, MagicMock
    from redis.exceptions import WatchError
    from ai_karen_engine.platform.memory.redis.redis_connection_manager import RedisConnectionManager

    manager = RedisConnectionManager()
    client = MagicMock()
    manager._client = client

    def pipeline(prior, conflict=False):
        pipe = MagicMock()
        pipe.__aenter__ = AsyncMock(return_value=pipe)
        pipe.__aexit__ = AsyncMock(return_value=False)
        pipe.watch = AsyncMock()
        pipe.get = AsyncMock(return_value=prior)
        pipe.execute = AsyncMock(side_effect=WatchError() if conflict else None,
                                 return_value=[True])
        return pipe

    first = pipeline("old", conflict=True)
    second = pipeline("newest")
    client.pipeline.side_effect = [first, second]
    assert await manager.conditional_set("key", "incoming", ex=600,
                                         should_replace=lambda prior: prior != "newest")
    first.execute.assert_awaited_once()
    second.execute.assert_not_awaited()
    assert client.pipeline.call_count == 2

    manager._degraded_mode = True
    assert not await manager.conditional_set("key", "incoming", ex=600,
                                             should_replace=lambda prior: True)
    assert manager._get_from_memory_cache("key") is None


@pytest.mark.asyncio
async def test_ordinary_writer_cannot_strip_committed_episode_provenance():
    from dataclasses import replace
    from datetime import timedelta

    adapter = RedisSTMAdapter(redis_manager=FakeRedisManager(), default_ttl_seconds=600)
    scope = STMScope("tenant", "user", "session")
    frame = EpisodeFrame.new(EpisodeObservation(
        tenant_id=scope.tenant_id, user_id=scope.user_id, session_id=scope.session_id,
        observed_at=datetime.now(timezone.utc), text="committed fact",
    ))
    committed = {**frame.to_dict(), "event_id": "event-1", "source_type": "chat_user",
                 "source_ref": "conversation-1"}
    assert await adapter.put_episode_if_newer(scope=scope, value=committed)
    later = replace(frame, updated_at=frame.updated_at + timedelta(seconds=1), last_text="ordinary")
    assert await adapter.save(later)
    assert await adapter.get_slot(scope=scope, slot=STMSlot.ACTIVE_EPISODE) == committed
    with pytest.raises(ValueError, match="committed source identity"):
        await adapter.put_slot(scope=scope, slot=STMSlot.ACTIVE_EPISODE,
                               value={**later.to_dict(), "event_id": "partial"})


@pytest.mark.asyncio
async def test_live_redis_ordered_episode_writers():
    import asyncio
    import os
    import uuid
    from dataclasses import replace
    from datetime import timedelta
    from redis.asyncio import Redis
    from ai_karen_engine.platform.memory.redis.redis_connection_manager import RedisConnectionManager

    if os.getenv("KAREN_TEST_REAL_REDIS_GRAPH") != "1":
        pytest.skip("requires explicitly enabled disposable Redis service")
    url = os.environ["REDIS_URL"]
    # Independent clients and managers, sharing only the isolated Redis key.
    managers = [RedisConnectionManager(redis_url=url) for _ in range(2)]
    for manager in managers:
        manager._client = Redis.from_url(url, decode_responses=True)
    adapters = [RedisSTMAdapter(redis_manager=manager, default_ttl_seconds=600)
                for manager in managers]
    scope = STMScope(str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()))
    frame = EpisodeFrame.new(EpisodeObservation(
        tenant_id=scope.tenant_id, user_id=scope.user_id, session_id=scope.session_id,
        observed_at=datetime.now(timezone.utc), text="initial",
    ))
    older = {**frame.to_dict(), "event_id": "old", "source_type": "chat_user",
             "source_ref": "conversation-1"}
    newer = {**replace(frame, updated_at=frame.updated_at + timedelta(seconds=1),
                      last_text="newer").to_dict(),
             "event_id": "new", "source_type": "chat_user", "source_ref": "conversation-1"}
    ordinary = replace(frame, updated_at=frame.updated_at + timedelta(seconds=2),
                       last_text="uncommitted")
    try:
        assert await managers[0]._client.ping()
        for _ in range(8):
            await adapters[0].delete_slot(scope=scope, slot=STMSlot.ACTIVE_EPISODE)
            assert all(await asyncio.gather(
                adapters[0].put_episode_if_newer(scope=scope, value=older),
                adapters[1].put_episode_if_newer(scope=scope, value=newer),
            ))
            assert await adapters[0].save(ordinary)
            assert await adapters[1].get_slot(scope=scope, slot=STMSlot.ACTIVE_EPISODE) == newer
    finally:
        await adapters[0].delete_slot(scope=scope, slot=STMSlot.ACTIVE_EPISODE)
        for manager in managers:
            await manager._client.aclose()
