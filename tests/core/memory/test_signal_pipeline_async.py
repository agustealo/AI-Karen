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
