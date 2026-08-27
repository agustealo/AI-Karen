from datetime import datetime, timezone

import pytest

from ai_karen_engine.core.memory.episodic import EpisodeFrame, EpisodeObservation
from ai_karen_engine.platform.memory.redis.episode_state import RedisEpisodeStateStore


class _Redis:
    def __init__(self):
        self.sessions = {}

    async def get_session(self, tenant_id, user_id, session_id):
        return self.sessions.get((tenant_id, user_id, session_id))

    async def set_session(self, tenant_id, user_id, sess_data, session_id, ttl_seconds=None):
        self.sessions[(tenant_id, user_id, session_id)] = dict(sess_data)
        self.last_ttl = ttl_seconds
        return True


def _frame():
    return EpisodeFrame.new(
        EpisodeObservation(
            tenant_id="tenant-a",
            user_id="user-a",
            session_id="session-a",
            observed_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
            text="start",
            goal_key="goal-a",
            project_key="project-a",
        )
    )


@pytest.mark.asyncio
async def test_episode_state_merges_with_existing_session_data():
    redis = _Redis()
    redis.sessions[("tenant-a", "user-a", "session-a")] = {"summary": "keep me"}
    store = RedisEpisodeStateStore(redis, ttl_seconds=900)
    frame = _frame()

    assert await store.save(frame) is True
    raw = redis.sessions[("tenant-a", "user-a", "session-a")]
    assert raw["summary"] == "keep me"
    assert raw[store.FIELD]["episode_group_id"] == frame.episode_group_id
    assert redis.last_ttl == 900

    restored = await store.load(
        tenant_id="tenant-a",
        user_id="user-a",
        session_id="session-a",
    )
    assert restored == frame


@pytest.mark.asyncio
async def test_episode_state_cannot_cross_scope():
    redis = _Redis()
    store = RedisEpisodeStateStore(redis)
    await store.save(_frame())

    assert (
        await store.load(
            tenant_id="tenant-b",
            user_id="user-a",
            session_id="session-a",
        )
        is None
    )
    assert (
        await store.load(
            tenant_id="tenant-a",
            user_id="user-b",
            session_id="session-a",
        )
        is None
    )


@pytest.mark.asyncio
async def test_clear_removes_only_episode_field():
    redis = _Redis()
    redis.sessions[("tenant-a", "user-a", "session-a")] = {"summary": "keep me"}
    store = RedisEpisodeStateStore(redis)
    await store.save(_frame())

    assert await store.clear(
        tenant_id="tenant-a",
        user_id="user-a",
        session_id="session-a",
    ) is True
    raw = redis.sessions[("tenant-a", "user-a", "session-a")]
    assert raw == {"summary": "keep me"}
