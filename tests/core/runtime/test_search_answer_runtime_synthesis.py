"""Grounded live search must not bypass execution budgets or source provenance."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime


@pytest.mark.asyncio
async def test_no_fetched_pages_never_calls_model():
    runtime = object.__new__(ChatRuntime)
    gateway = SimpleNamespace(generate=AsyncMock())
    runtime._composition = SimpleNamespace(expression_gateway=gateway)
    meter = SimpleNamespace(consume_model_call=AsyncMock(return_value=True))
    request = SimpleNamespace(
        messages=[{"role": "user", "content": "Jamaica history"}],
        context=SimpleNamespace(correlation_id="test", request_id="test"),
    )
    retrieved = SimpleNamespace(sources=[
        {"url": "https://example.org/history", "evidence_level": "search_snippet", "content": "Unfetched"}
    ])
    result = await runtime._synthesize_search_evidence(request, SimpleNamespace(), meter, retrieved)
    assert result is None
    gateway.generate.assert_not_called()
    meter.consume_model_call.assert_not_called()
