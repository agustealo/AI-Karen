"""Tests for canonical NeuroRecall scope isolation."""

import pytest

from ai_karen_engine.core.memory.retrieval.neuro_recall import (
    NeuroRecall,
    RecallRequest,
    RecallScopeError,
)
from ai_karen_engine.core.memory.types import MemoryEntry, MemoryMetadata


class _FakeRetriever:
    def __init__(self, memories):
        self.memories = memories
        self.seen_query = None

    async def recall(self, query):
        self.seen_query = query
        return list(self.memories)


def _memory(memory_id: str, tenant_id: str, user_id: str) -> MemoryEntry:
    return MemoryEntry(
        id=memory_id,
        content=f"memory:{memory_id}",
        metadata=MemoryMetadata(
            tenant_id=tenant_id,
            user_id=user_id,
            source="test",
            custom={"source_store": "test"},
        ),
    )


@pytest.mark.asyncio
async def test_recall_requires_tenant_scope():
    service = NeuroRecall(_FakeRetriever([]))
    with pytest.raises(RecallScopeError, match="tenant_id"):
        await service.recall(
            RecallRequest(query="hello", tenant_id="", user_id="user-1")
        )


@pytest.mark.asyncio
async def test_recall_requires_user_scope():
    service = NeuroRecall(_FakeRetriever([]))
    with pytest.raises(RecallScopeError, match="user_id"):
        await service.recall(
            RecallRequest(query="hello", tenant_id="tenant-1", user_id="")
        )


@pytest.mark.asyncio
async def test_recall_drops_cross_tenant_and_cross_user_results():
    retriever = _FakeRetriever(
        [
            _memory("allowed", "tenant-1", "user-1"),
            _memory("wrong-tenant", "tenant-2", "user-1"),
            _memory("wrong-user", "tenant-1", "user-2"),
        ]
    )
    service = NeuroRecall(retriever)

    result = await service.recall(
        RecallRequest(
            query="hello",
            tenant_id="tenant-1",
            user_id="user-1",
            correlation_id="corr-1",
        )
    )

    assert [memory.id for memory in result.memories] == ["allowed"]
    assert retriever.seen_query.tenant_id == "tenant-1"
    assert retriever.seen_query.user_id == "user-1"
    assert result.provenance[0]["memory_id"] == "allowed"


@pytest.mark.asyncio
async def test_retrieval_failure_is_degraded_not_cross_scope_fallback():
    class _BrokenRetriever:
        async def recall(self, query):
            raise RuntimeError("backend exploded")

    result = await NeuroRecall(_BrokenRetriever()).recall(
        RecallRequest(query="hello", tenant_id="tenant-1", user_id="user-1")
    )

    assert result.memories == ()
    assert result.degraded is True
    assert result.degradation_reason == "retrieval_unavailable"
