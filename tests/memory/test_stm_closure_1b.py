from __future__ import annotations

from typing import Any

import pytest

from ai_karen_engine.core.memory.projections.hot_state_worker import HotStateWorker
from ai_karen_engine.core.memory.retrieval.retrieval_router import HybridRetrievalRouter
from ai_karen_engine.core.memory.stm import STMScope, STMSlot
from ai_karen_engine.core.memory.types import (
    MemoryNamespace,
    MemoryQuery,
    MemoryType,
    create_memory_entry,
)


class FakeSTM:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        self._degraded = False

    @staticmethod
    def _key(scope: STMScope, slot: STMSlot) -> tuple[str, str, str, str]:
        scope.validate()
        return (scope.tenant_id, scope.user_id, scope.session_id, slot.value)

    async def get_slot(self, *, scope: STMScope, slot: STMSlot):
        return self.values.get(self._key(scope, slot))

    async def put_slot(
        self,
        *,
        scope: STMScope,
        slot: STMSlot,
        value: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> bool:
        del ttl_seconds
        self.values[self._key(scope, slot)] = dict(value)
        return True

    async def put_episode_if_newer(self, *, scope: STMScope, value: dict[str, Any]) -> bool:
        from ai_karen_engine.core.memory.episodic import EpisodeFrame
        prior = self.values.get(self._key(scope, STMSlot.ACTIVE_EPISODE))
        if prior and EpisodeFrame.from_dict(prior).updated_at >= EpisodeFrame.from_dict(value).updated_at:
            return True
        return await self.put_slot(scope=scope, slot=STMSlot.ACTIVE_EPISODE, value=value)

    async def delete_slot(self, *, scope: STMScope, slot: STMSlot) -> bool:
        return self.values.pop(self._key(scope, slot), None) is not None

    def degraded(self) -> bool:
        return self._degraded


class EmptyGraph:
    async def get_entity_context(self, **_: Any) -> list[dict[str, Any]]:
        return []


class EmptyEventSource:
    async def fetch_many(self, **_: Any) -> dict[str, dict[str, Any]]:
        return {}


class EmptyResolver:
    async def resolve_cues(self, **_: Any) -> list[Any]:
        return []


@pytest.mark.asyncio
async def test_hot_projection_writes_only_canonical_recent_context_slot() -> None:
    stm = FakeSTM()
    worker = HotStateWorker(stm)

    assert await worker.project(
        {
            "event_id": "event-1",
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "session_id": "session-a",
            "source_type": "chat",
            "payload": {"text": "remember this", "signal_type": "fact"},
        }
    )

    scope = STMScope("tenant-a", "user-a", "session-a")
    assert await stm.get_slot(scope=scope, slot=STMSlot.RECENT_CONTEXT) is not None
    assert await stm.get_slot(scope=scope, slot=STMSlot.ACTIVE_EPISODE) is None
    assert len(stm.values) == 1


@pytest.mark.asyncio
async def test_hot_projection_does_not_invent_global_stm_without_session() -> None:
    stm = FakeSTM()
    worker = HotStateWorker(stm)

    assert await worker.project(
        {
            "event_id": "event-1",
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "payload": {"text": "durable only"},
        }
    )
    assert stm.values == {}


@pytest.mark.asyncio
async def test_stm_recall_is_slot_typed_and_excludes_tool_state() -> None:
    stm = FakeSTM()
    scope = STMScope("tenant-a", "user-a", "session-a")
    await stm.put_slot(
        scope=scope,
        slot=STMSlot.RECENT_CONTEXT,
        value={"latest": {
            "event_id": "event-1",
            "content": "recent conversation",
            "source_type": "chat_user",
            "source_ref": "conversation-1",
        }},
    )
    await stm.put_slot(
        scope=scope,
        slot=STMSlot.ACTIVE_GOAL,
        value={"goal": "finish memory closure"},
    )
    await stm.put_slot(
        scope=scope,
        slot=STMSlot.TOOL_STATE,
        value={"tool": "shell", "secret_state": "must not become recall"},
    )

    class CanonicalEventSource:
        async def fetch_many(self, *, tenant_id, user_id, event_ids, for_current_recall=False):
            assert for_current_recall is True
            assert (tenant_id, user_id) == ("tenant-a", "user-a")
            assert event_ids == ["event-1"]
            return {
                "event-1": {
                    "event_id": "event-1",
                    "source_type": "chat_user",
                    "source_ref": "conversation-1",
                    "payload": {"content": "recent conversation"},
                }
            }

    router = HybridRetrievalRouter(
        stm=stm,
        graph=EmptyGraph(),
        event_source=CanonicalEventSource(),
        entity_resolver=EmptyResolver(),
    )
    results = await router._query_stm(
        MemoryQuery(
            text="what are we doing",
            tenant_id="tenant-a",
            user_id="user-a",
            session_id="session-a",
        )
    )

    by_slot = {item.metadata.custom["stm_slot"]: item for item in results}
    assert set(by_slot) == {"recent_context", "active_goal"}
    assert by_slot["recent_context"].memory_type is MemoryType.EPISODIC
    assert by_slot["active_goal"].memory_type is MemoryType.SEMANTIC
    assert all(item.namespace is MemoryNamespace.SHORT_TERM for item in results)
    assert all("secret_state" not in item.content for item in results)


def test_memory_query_has_typed_session_scope() -> None:
    query = MemoryQuery(
        tenant_id="tenant-a",
        user_id="user-a",
        session_id="session-a",
    )
    assert query.session_id == "session-a"


def test_memory_entry_factory_rejects_implicit_tenant() -> None:
    with pytest.raises(ValueError, match="explicit non-default tenant_id"):
        create_memory_entry("unsafe")
    with pytest.raises(ValueError, match="explicit non-default tenant_id"):
        create_memory_entry("unsafe", tenant_id="default")

    entry = create_memory_entry("safe", tenant_id="tenant-a", user_id="user-a")
    assert entry.metadata is not None
    assert entry.metadata.tenant_id == "tenant-a"


@pytest.mark.asyncio
async def test_private_episode_projection_uses_committed_assertion_and_lineage():
    stm = FakeSTM()
    worker = HotStateWorker(stm)
    event = {
        "event_id": "event-1", "tenant_id": "tenant-a", "user_id": "user-a",
        "session_id": "session-a", "source_type": "chat_user",
        "source_ref": "conversation-1", "project_episode_state": True,
        "payload": {"text": "unadmitted interaction", "metadata": {
            "episode_group_id": "episode-1",
            "episode_started_at": "2026-11-25T01:00:00+00:00",
            "episode_updated_at": "2026-11-25T01:01:00+00:00",
            "episode_turn_count": 2,
        }},
    }
    assertion = {"event_id": "event-1", "assertion_id": "assertion-1", "text": "admitted fact"}
    assert await worker.project(event, assertion)
    scope = STMScope("tenant-a", "user-a", "session-a")
    frame = await stm.get_slot(scope=scope, slot=STMSlot.ACTIVE_EPISODE)
    assert frame["last_text"] == "admitted fact"
    assert frame["event_id"] == "event-1"
    assert frame["source_type"] == "chat_user"
    assert frame["source_ref"] == "conversation-1"
    assert frame["turn_count"] == 2
    assert "unadmitted interaction" not in repr(frame)

    older = {**event, "event_id": "event-old", "payload": {"metadata": {
        **event["payload"]["metadata"], "episode_updated_at": "2026-11-25T01:00:30+00:00",
    }}}
    assert await worker.project(older, {**assertion, "event_id": "event-old", "text": "old fact"})
    assert await stm.get_slot(scope=scope, slot=STMSlot.ACTIVE_EPISODE) == frame


@pytest.mark.asyncio
async def test_private_episode_projection_rejects_mismatched_assertion():
    stm = FakeSTM()
    worker = HotStateWorker(stm)
    event = {
        "event_id": "event-1", "tenant_id": "tenant-a", "user_id": "user-a",
        "session_id": "session-a", "source_type": "chat_user",
        "source_ref": "conversation-1", "project_episode_state": True,
    }
    assert not await worker.project(event, {"event_id": "foreign", "text": "foreign fact"})
    assert await stm.get_slot(
        scope=STMScope("tenant-a", "user-a", "session-a"), slot=STMSlot.ACTIVE_EPISODE,
    ) is None
