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
