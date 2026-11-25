"""Runtime-level proof: configured reasoning strategies cannot forge model receipts."""

from __future__ import annotations

from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("reported_calls", [0, 1])
@pytest.mark.parametrize(
    ("executed", "modes", "verifier_executed"),
    [
        ([], ("verification",), False),
        (["metacognition"], ("verification",), False),
        (["verify"], ("verification",), True),
        (["verify"], ("evidence_synthesis",), False),
    ],
)
async def test_reasoning_strategy_cannot_forge_observed_model_provenance(
    reported_calls, executed, modes, verifier_executed,
):
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
        diagnostics={
            "model_calls": reported_calls,
            "steps": 1,
            "strategies_executed": executed,
        },
        status="success",
        reasoning_id="reason-1",
    )
    activation = SimpleNamespace(
        reasoning_modes=modes,
        request_metadata={},
        runtime_metadata={
            "reasoning_activation": "runtime_composed",
            "soft_reasoning_provider": "ollama-local",
            "soft_reasoning_model": "configured-not-observed",
            "actual_provider": "forged-model-provider",
            "actual_model": "forged-model",
            "response_source": "model",
            "fallback_level": 0,
            "verification_strategy_executed": not verifier_executed,
            "reasoning_id": "forged-reason",
            "reasoning_status": "failed",
            "reasoning_model_calls": 99,
            "reasoning_steps": 99,
            "execution_spans": [{"name": "forged"}],
        },
        executor=SimpleNamespace(execute=AsyncMock(return_value=result)),
    )
    activation_calls = []

    def activate(**kwargs):
        activation_calls.append(kwargs)
        return activation

    fake_bridge = SimpleNamespace(activate=activate)
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
    bridge_module = ModuleType("ai_karen_engine.core.runtime.reasoning_bridge")
    bridge_module.get_runtime_reasoning_bridge = lambda: fake_bridge
    with patch.dict(
        "sys.modules",
        {"ai_karen_engine.core.runtime.reasoning_bridge": bridge_module},
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
    assert metadata["reasoning_steps"] == 1
    assert metadata["reasoning_id"] == "reason-1"
    assert metadata["reasoning_status"] == "success"
    assert metadata["execution_spans"][0]["name"] == "reasoning_executor"
    assert metadata["verification_strategy_executed"] is verifier_executed
    assert metadata["reasoning_model_attribution_status"] == (
        "unverified" if reported_calls else "not_executed"
    )
    assert activation.executor.execute.await_count == 1
    assert len(activation_calls) == 1
    assert activation_calls[0]["preferred_provider"] == "ollama-local"
    assert activation_calls[0]["preferred_model"] == "requested-model"
    assert activation_calls[0]["plan"] is plan
    assert activation_calls[0]["decision"] is decision
    assert activation_calls[0]["authenticated_context"] is request.context
    assert activation_calls[0]["execution_meter"] is meter
