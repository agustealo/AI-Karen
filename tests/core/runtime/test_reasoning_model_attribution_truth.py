"""Runtime-level proof: configured reasoning strategies cannot forge model receipts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import ai_karen_engine.core.runtime.reasoning_bridge as reasoning_bridge

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("reported_calls", [0, 1])
async def test_reasoning_strategy_cannot_forge_observed_model_provenance(reported_calls):
    """No executable provider receipt means no claimed actual provider/model."""
    runtime = ChatRuntime.__new__(ChatRuntime)
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "Explain this."}],
        context=ChatExecutionContext(
            user_id="user-1", tenant_id="tenant-1", session_id="session-1",
            conversation_id="22222222-2222-4222-8222-222222222222",
            request_id="request-1", correlation_id="correlation-1",
        ),
        preferred_provider="ollama-local",
        preferred_model="requested-model",
    )
    result = SimpleNamespace(
        summary="A reasoning-only summary.",
        hypotheses=[],
        diagnostics={"model_calls": reported_calls, "steps": 1},
        status="success",
        reasoning_id="reason-1",
    )
    activation = SimpleNamespace(
        reasoning_modes=("evidence_synthesis",),
        request_metadata={},
        runtime_metadata={
            "reasoning_activation": "runtime_composed",
            "soft_reasoning_provider": "ollama-local",
            "soft_reasoning_model": "configured-not-observed",
            "actual_provider": "forged-model-provider",
            "actual_model": "forged-model",
            "response_source": "model",
            "fallback_level": 0,
        },
        executor=SimpleNamespace(execute=AsyncMock(return_value=result)),
    )
    fake_bridge = SimpleNamespace(activate=lambda **kwargs: activation)
    decision = SimpleNamespace(
        memory_top_k=5, reasoning_depth="standard",
        tool_requirements=[], plugin_candidates=[],
        policy_decision_id="policy-1", max_steps=5,
        time_budget_ms=30000,
    )
    plan = SimpleNamespace(
        budget=SimpleNamespace(
            max_model_calls=3, max_duration_ms=30000,
            max_output_tokens=256,
        ),
    )
    meter = SimpleNamespace(
        consume_model_call=AsyncMock(return_value=True),
        consume_reasoning_step=AsyncMock(return_value=True),
        check_duration=AsyncMock(return_value=True),
    )
    with patch(
        "ai_karen_engine.core.runtime.reasoning_bridge.get_runtime_reasoning_bridge",
        return_value=fake_bridge,
    ):
        answer, metadata = await runtime._run_reasoning(
            request, decision, plan, meter,
        )

    assert answer == "A reasoning-only summary."
    assert metadata["requested_provider"] == "ollama-local"
    assert metadata["requested_model"] == "requested-model"
    assert metadata["actual_provider"] is None
    assert metadata["actual_model"] is None
    assert metadata["response_source"] == "reasoning"
    assert metadata["reasoning_model_calls"] == reported_calls
    assert metadata["reasoning_model_attribution_status"] == (
        "unverified" if reported_calls else "not_executed"
    )
    assert activation.executor.execute.await_count == 1
