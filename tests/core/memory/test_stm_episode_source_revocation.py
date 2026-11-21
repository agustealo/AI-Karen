"""Verify session hot-state replay cannot bypass canonical source governance."""

from __future__ import annotations

import pytest

from ai_karen_engine.core.memory.retrieval.neuro_recall import NeuroRecall, RecallRequest
from ai_karen_engine.core.memory.retrieval.retrieval_router import HybridRetrievalRouter
from ai_karen_engine.core.memory.stm import STMSlot
from ai_karen_engine.core.memory.types import MemoryQuery


class _STM:
    def __init__(self, latest):
        self.latest = latest

    async def get_slot(self, *, scope, slot):
        assert scope.tenant_id == "tenant-1"
        assert scope.user_id == "user-1"
        assert scope.session_id == "session-1"
        if slot == STMSlot.RECENT_CONTEXT:
            return {"latest": self.latest}
        return None


class _EventSource:
    def __init__(self):
        self.current = None
        self.calls = 0

    async def fetch_many(self, *, tenant_id, user_id, event_ids):
        self.calls += 1
        assert (tenant_id, user_id) == ("tenant-1", "user-1")
        assert event_ids == ["event-1"]
        return {"event-1": self.current} if self.current is not None else {}


class _SourceACL:
    allowed = True

    async def authorize(self, memory, request):
        provenance = memory.metadata.custom["provenance"]
        assert provenance["source_type"] == "web"
        assert provenance["source_ref"] == "document-1"
        assert (request.tenant_id, request.user_id) == ("tenant-1", "user-1")
        return self.allowed


def _router(*, source_type="web", source_ref="document-1"):
    latest = {
        "event_id": "event-1", "content": "remember this episode",
        "source_type": source_type, "source_ref": source_ref,
    }
    events = _EventSource()
    events.current = {
        "event_id": "event-1", "source_type": source_type,
        "source_ref": source_ref, "payload": {"content": "remember this episode"},
    }
    router = HybridRetrievalRouter(
        stm=_STM(latest), graph=object(), event_source=events,
        entity_resolver=object(),
    )
    return router, events, latest


def _query():
    return MemoryQuery(
        text="remember this episode",
        tenant_id="tenant-1", user_id="user-1", session_id="session-1",
    )


def _request():
    return RecallRequest(
        query="remember this episode",
        tenant_id="tenant-1", user_id="user-1",
        session_id="session-1",
    )


@pytest.mark.asyncio
async def test_stm_recent_episode_requires_live_source_grant_and_rechecks_revocation():
    router, events, latest = _router()
    candidates = await router._query_stm(_query())
    assert len(candidates) == 1
    assert candidates[0].metadata.custom["provenance"]["event_id"] == "event-1"
    assert candidates[0].metadata.custom["provenance"]["source_ref"] == "document-1"

    class _Retriever:
        async def recall(self, query):
            return await router._query_stm(query)

    no_grant = await NeuroRecall(_Retriever()).recall(_request())
    assert no_grant.memories == ()
    acl = _SourceACL()
    recall = NeuroRecall(_Retriever(), source_authorizer=acl)
    allowed = await recall.recall(_request())
    assert len(allowed.memories) == 1
    acl.allowed = False
    denied = await recall.recall(_request())
    assert denied.memories == ()
    assert events.calls >= 4


@pytest.mark.asyncio
async def test_stm_recent_episode_canonical_source_mismatch_and_consent_revocation_fail_closed():
    router, events, latest = _router()
    latest["source_type"] = "chat_user"
    assert await router._query_stm(_query()) == []
    latest["source_type"] = "web"
    latest["content"] = "forged episode content"
    assert await router._query_stm(_query()) == []
    latest["content"] = "remember this episode"
    events.current = None
    assert await router._query_stm(_query()) == []


@pytest.mark.asyncio
async def test_stm_recent_episode_direct_chat_remains_available_after_canonical_validation():
    router, events, latest = _router(source_type="chat_user", source_ref="conversation-1")

    class _Retriever:
        async def recall(self, query):
            return await router._query_stm(query)

    result = await NeuroRecall(_Retriever()).recall(_request())
    assert len(result.memories) == 1
    assert result.memories[0].content == "remember this episode"


@pytest.mark.asyncio
async def test_stm_recent_episode_missing_canonical_event_or_refuses_on_error():
    router, events, latest = _router()
    latest.pop("event_id")
    assert await router._query_stm(_query()) == []
    latest["event_id"] = "event-1"
    events.current = {"source_type": "web", "source_ref": "document-1", "payload": {}}
    assert await router._query_stm(_query()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("raw_text", [
    "  remember this episode", "remember this episode\n",
    "\n remember this episode \n",
])
async def test_stm_recent_episode_preserves_canonical_whitespace_before_normalizing_output(raw_text):
    router, events, latest = _router(source_type="chat_user", source_ref="conversation-1")
    latest["content"] = raw_text
    events.current["payload"]["content"] = raw_text
    candidates = await router._query_stm(_query())
    assert len(candidates) == 1
    assert candidates[0].content == raw_text.strip()

    class _Retriever:
        async def recall(self, query):
            return await router._query_stm(query)

    selected = await NeuroRecall(_Retriever()).recall(_request())
    assert len(selected.memories) == 1
    assert selected.memories[0].content == raw_text.strip()
