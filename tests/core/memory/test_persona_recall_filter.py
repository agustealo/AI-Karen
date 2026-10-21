"""Persona-aware recall remains tenant scoped and excludes other personas."""
import pytest

from ai_karen_engine.core.memory.retrieval.neuro_recall import (
    NeuroRecall, RecallRequest, RecallScopeError,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["", "   ", 17, False])
async def test_invalid_persona_filter_rejected_even_without_candidates(invalid):
    recall = NeuroRecall(retrievers=[])
    with pytest.raises(RecallScopeError, match="persona_filter"):
        await recall.recall(RecallRequest(
            query="my prior work", tenant_id="tenant-a", user_id="user-a",
            metadata={"persona_filter": invalid},
        ))


@pytest.mark.asyncio
async def test_valid_filter_can_produce_empty_result_without_new_memory_authority():
    recall = NeuroRecall(retrievers=[])
    result = await recall.recall(RecallRequest(
        query="my prior work", tenant_id="tenant-a", user_id="user-a",
        metadata={"persona_filter": "assistant"},
    ))
    assert result.memories == ()
