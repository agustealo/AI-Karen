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


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["search.general", "search.weather", "time.current"])
async def test_canonical_composer_identical_metadata_in_both_transports(intent):
    runtime = object.__new__(ChatRuntime)
    request, plan, meter = object(), object(), object()
    decision = SimpleNamespace(intent=intent)
    result = DirectCapabilityResult(
        handled=True, success=True, text="Evidence-only response",
        source="tool", source_id="approved_tool",
    )
    generated = ("Grounded response", {
        "actual_provider": "ollama", "actual_model": "verified-model",
        "response_source": "grounded_observation_model",
    })
    with patch.object(
        runtime, "_synthesize_search_evidence",
        new_callable=AsyncMock, return_value=generated,
    ) as synthesize:
        answer, meta = await runtime._compose_direct_capability_answer(
            request, decision, plan, meter, result, result.normalized_metadata()
        )
    assert answer == "Grounded response"
    assert meta["actual_model"] == "verified-model"
    assert meta["response_source"] == "grounded_observation_model"
    synthesize.assert_awaited_once_with(request, decision, plan, meter, result)


@pytest.mark.asyncio
async def test_canonical_composer_does_not_attempt_generation_on_failed_tool():
    runtime = object.__new__(ChatRuntime)
    result = DirectCapabilityResult(
        handled=True, success=False, text="Live data unavailable",
        degraded=True, source="capability_unavailable",
    )
    with patch.object(runtime, "_synthesize_search_evidence", new_callable=AsyncMock) as synthesize:
        answer, meta = await runtime._compose_direct_capability_answer(
            object(), SimpleNamespace(intent="search.weather"),
            object(), object(), result, result.normalized_metadata()
        )
    assert answer == "Live data unavailable"
    assert meta["actual_model"] is None
    assert meta["degraded_mode"] is True
    synthesize.assert_not_called()



@pytest.mark.asyncio
@pytest.mark.parametrize("verified", [True, False])
async def test_live_direct_stream_presents_only_valid_authorized_surface_before_completion(
    verified,
):
    """The same bounded envelope reaches stream and persistence metadata."""
    runtime = object.__new__(ChatRuntime)
    request = SimpleNamespace(
        context=SimpleNamespace(
            correlation_id="corr-live", request_id="req-live",
            tenant_id="tenant", user_id="user",
        ),
        messages=[{"role": "user", "content": "Weather now"}],
    )
    decision = SimpleNamespace(intent="search.weather", cognitive_context=None)
    result = DirectCapabilityResult(
        handled=True, success=True, text="Verified observation",
        source="tool", source_id="weather_tool",
    )
    envelope = {
        "schema_version": 1,
        "presentation_id": "weather-req-live",
        "component_type": "weather.observation",
        "evidence_ref": "req-live:weather_tool",
        "correlation_id": "corr-live",
        "data": {
            "location": "Detroit",
            "temperature_f": 61.0 if verified else 900.0,
        },
    }
    metadata = {}
    executor = SimpleNamespace(execute=AsyncMock(return_value=result))
    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_direct_capability_executor",
        return_value=executor,
    ), patch.object(
        runtime, "_collect_authorized_surface_parts",
        return_value=[envelope],
    ), patch.object(
        runtime, "_pending_clarification_from_result", return_value=None,
    ), patch.object(
        runtime, "_synthesize_search_evidence",
        new_callable=AsyncMock, return_value=None,
    ) as synthesis:
        chunks = [
            chunk async for chunk in runtime._run_direct_capability_stream(
                request, decision, object(), object(), metadata,
            )
        ]
    synthesis.assert_awaited_once()
    assert chunks[0].type == "content"
    assert chunks[0].content == "Verified observation"
    assert chunks[0].metadata["response_source"] == "tool"
    if verified:
        assert [chunk.type for chunk in chunks] == ["content", "presentation"]
        assert chunks[1].metadata["presentation_verified"] is True
        assert chunks[1].metadata["presentation"]["presentation_id"] == envelope["presentation_id"]
        assert chunks[1].metadata["presentation"]["correlation_id"] == "corr-live"
        assert (
            chunks[1].metadata["presentation"]
            == metadata["structured_content"]["presentation"]
        )
    else:
        # Invalid tool envelopes must not become apparently verified UI events.
        assert [chunk.type for chunk in chunks] == ["content"]
