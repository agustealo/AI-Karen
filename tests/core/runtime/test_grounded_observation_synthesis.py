"""Grounded weather and time must use honest, validated model receipts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityResult


def _fixture(intent, output, *, allowed=True):
    runtime = object.__new__(ChatRuntime)
    gateway = SimpleNamespace(generate=AsyncMock(return_value=SimpleNamespace(
        text=output, provider="ollama", model="local-model",
        runtime_engine="ollama", engine_id="ollama", degraded=False,
        degradation_reason=None,
    )))
    runtime._composition = SimpleNamespace(expression_gateway=gateway)
    request = SimpleNamespace(
        messages=[{"role": "user", "content": "What's it like now?"}],
        context=SimpleNamespace(correlation_id="corr", request_id="req"),
        preferred_provider="ollama", preferred_model="local-model",
        max_tokens=160, temperature=0.1,
    )
    decision = SimpleNamespace(
        intent=intent, required_capabilities=[], forbidden_capabilities=[],
        time_budget_ms=30000,
    )
    source = "tool"
    source_id = "weather_tool" if intent == "search.weather" else "time_tool"
    plan = SimpleNamespace(
        allowed_tools=[source_id] if allowed else [], allowed_plugins=[],
    )
    payload = (
        {"extractedData": {"location": "NYC", "temperature": 54.3,
                            "humidity": 47, "observed_at": "2026-10-22T10:30"}}
        if intent == "search.weather" else
        {"formatted": "10:30 AM", "date": "2026-10-22", "timezone": "America/New_York"}
    )
    retrieved = DirectCapabilityResult(
        handled=True, success=True, source=source, source_id=source_id,
        text="Verified observation", payload=payload,
        attempts=[{"type": source, "id": source_id, "status": "success"}],
    )
    meter = SimpleNamespace(
        consume_model_call=AsyncMock(return_value=True),
        check_duration=AsyncMock(return_value=True),
    )
    return runtime, gateway, request, decision, plan, meter, retrieved


@pytest.mark.asyncio
@pytest.mark.parametrize("intent,answer", [
    ("search.weather", "It's 54.3 degrees in NYC, humidity 47%."),
    ("time.current", "The local time is 10:30 AM on 2026-10-22."),
])
async def test_verified_observation_is_composed_with_actual_model_receipt(intent, answer):
    runtime, gateway, request, decision, plan, meter, result = _fixture(intent, answer)
    with patch.object(ChatRuntime, "_resolve_chat_generation_max_tokens", return_value=160):
        composed = await runtime._synthesize_search_evidence(
            request, decision, plan, meter, result
        )
    assert composed is not None
    text, metadata = composed
    assert text == answer
    assert metadata["actual_provider"] == "ollama"
    assert metadata["actual_model"] == "local-model"
    assert metadata["response_source"] == "grounded_observation_model"
    gateway.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_hallucinated_measurement_rejected():
    runtime, gateway, request, decision, plan, meter, result = _fixture(
        "search.weather", "It's 99 degrees in NYC."
    )
    with patch.object(ChatRuntime, "_resolve_chat_generation_max_tokens", return_value=160):
        assert await runtime._synthesize_search_evidence(
            request, decision, plan, meter, result
        ) is None
    gateway.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_unapproved_source_never_reaches_model():
    runtime, gateway, request, decision, plan, meter, result = _fixture(
        "search.weather", "It's 54.3 degrees.", allowed=False
    )
    assert await runtime._synthesize_search_evidence(
        request, decision, plan, meter, result
    ) is None
    gateway.generate.assert_not_called()
    meter.consume_model_call.assert_not_called()


@pytest.mark.asyncio
async def test_missing_provider_receipt_rejected():
    runtime, gateway, request, decision, plan, meter, result = _fixture(
        "time.current", "It's 10:30 AM."
    )
    gateway.generate.return_value.provider = None
    with patch.object(ChatRuntime, "_resolve_chat_generation_max_tokens", return_value=160):
        assert await runtime._synthesize_search_evidence(
            request, decision, plan, meter, result
        ) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("intent,answer", [
    ("search.weather", "It's 99 degrees in NYC."),
    ("search.weather", "Humidity is 88%."),
    ("time.current", "It is 11:30 AM."),
    ("time.current", "The date is 2027-10-22."),
])
async def test_unobserved_numeric_claims_never_leave_model_gateway(intent, answer):
    runtime, gateway, request, decision, plan, meter, result = _fixture(
        intent, answer
    )
    with patch.object(ChatRuntime, "_resolve_chat_generation_max_tokens", return_value=160):
        composed = await runtime._synthesize_search_evidence(
            request, decision, plan, meter, result
        )
    assert composed is None
    gateway.generate.assert_awaited_once()
