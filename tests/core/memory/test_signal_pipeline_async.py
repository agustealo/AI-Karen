from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ai_karen_engine.core.memory.signals.signal_models import MemorySignal
from ai_karen_engine.core.memory.signals.signal_pipeline import SignalPipeline


class _AsyncAwareRunner:
    def __init__(self) -> None:
        self.saw_coroutine_function = False

    async def run_stage(self, *, func: Any, text: str, **_: Any) -> Any:
        self.saw_coroutine_function = asyncio.iscoroutinefunction(func)
        return await func(text)


@pytest.mark.asyncio
async def test_signal_pipeline_passes_async_extractor_directly() -> None:
    pipeline = SignalPipeline()
    runner = _AsyncAwareRunner()
    pipeline.safe_runner = runner

    expected = MemorySignal(
        text="prefer concise responses",
        signal_type="preference",
        confidence=0.75,
        scope="user",
        metadata={"source": "test"},
    )

    async def extract(text: str) -> list[MemorySignal]:
        assert text == "I prefer concise responses."
        return [expected]

    pipeline.memory_extractor.extract = extract

    result = await pipeline.process_text(
        "I prefer concise responses.",
        tenant_id="tenant-a",
        user_id="user-a",
    )

    assert runner.saw_coroutine_function is True
    assert result.status == "success"
    assert result.signals == [expected]
    assert result.errors == []


class _CanonicalTupleEntityParser:
    async def parse_message(self, text: str):
        from ai_karen_engine.core.intelligence.linguistic.contracts import (
            ParsedMessage,
        )

        assert "lighthouse" in text
        return ParsedMessage(
            entities=[("Lake Erie", "LOC"), ("Detroit", "GPE")],
            dependencies=[],
        )


@pytest.mark.asyncio
async def test_spacy_entity_tuples_become_typed_memory_and_vault_entities() -> None:
    """The canonical tuple contract must never reach NeuroVault unchanged."""
    from ai_karen_engine.core.memory.formation.service import MemoryFormationService
    from ai_karen_engine.core.memory.signals.memory_signal_extractor import (
        MemorySignalExtractor,
    )

    text = "A lighthouse near Lake Erie helps ships navigate by Detroit."
    extractor = MemorySignalExtractor(spacy_service=_CanonicalTupleEntityParser())

    signals = await extractor.extract(text)
    entities = [signal for signal in signals if signal.signal_type == "entity"]
    assert len(entities) == 1
    assert entities[0].entities == [
        {"text": "Lake Erie", "label": "LOC"},
        {"text": "Detroit", "label": "GPE"},
    ]

    entry = MemoryFormationService._entry_from_signal(
        signal=entities[0],
        score=0.8,
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        source_type="chat_user",
        source_ref="session-1",
        metadata={},
        session_id="session-1",
        conversation_id="00000000-0000-0000-0000-000000000003",
    )
    assert entry.entities == ["Lake Erie", "Detroit"]
    assert entry.metadata.custom["signal_type"] == "entity"
    assert entry.metadata.custom["entities"] == [
        {"text": "Lake Erie", "label": "LOC"},
        {"text": "Detroit", "label": "GPE"},
    ]
