"""Direct-capability streaming must share grounded search composition and attribution."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityResult


@pytest.mark.asyncio
@pytest.mark.parametrize("generated", [True, False])
async def test_stream_search_composes_once_or_truthfully_reports_tool_only(generated):
    runtime = object.__new__(ChatRuntime)
    request = SimpleNamespace(
        context=SimpleNamespace(
            correlation_id="corr-search", request_id="req-search",
            tenant_id="tenant", user_id="user",
        ),
    )
    decision = SimpleNamespace(intent="search.general")
    plan = SimpleNamespace()
    meter = SimpleNamespace()
    result = DirectCapabilityResult(
        handled=True, success=True, text="Raw search tool result",
        source="tool", source_id="web_search",
    )
    executor = SimpleNamespace(execute=AsyncMock(return_value=result))
    synthesis = (
        ("Grounded, cited answer.", {
            "actual_provider": "ollama",
            "actual_model": "command-r7b:latest",
            "runtime_engine": "ollama",
            "response_source": "grounded_search_model",
        }) if generated else None
    )
    metadata = {}
    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_direct_capability_executor",
        return_value=executor,
    ), patch.object(
        runtime, "_synthesize_search_evidence",
        new_callable=AsyncMock, return_value=synthesis,
    ) as composer, patch.object(
        runtime, "_verified_planner_presentation", return_value=None,
    ), patch.object(
        runtime, "_verified_weather_presentation", return_value=None,
    ), patch.object(
        runtime, "_pending_clarification_from_result", return_value=None,
    ):
        chunks = [
            chunk async for chunk in runtime._run_direct_capability_stream(
                request, decision, plan, meter, metadata
            )
        ]
    composer.assert_awaited_once_with(request, decision, plan, meter, result)
    assert len(chunks) == 1
    assert chunks[0].content == (
        "Grounded, cited answer." if generated else "Raw search tool result"
    )
    assert chunks[0].metadata["actual_model"] == (
        "command-r7b:latest" if generated else None
    )
    assert metadata["actual_model"] == (
        "command-r7b:latest" if generated else None
    )
    assert chunks[0].metadata["response_source"] == (
        "grounded_search_model" if generated else "tool"
    )
