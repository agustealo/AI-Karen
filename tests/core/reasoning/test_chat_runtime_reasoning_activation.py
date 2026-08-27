from __future__ import annotations

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.contracts import ExecutionTopology
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision


def test_chat_runtime_plan_preserves_authorized_reasoning_modes_and_model_budget() -> None:
    runtime = ChatRuntime.__new__(ChatRuntime)
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "reason about this"}],
        context=ChatExecutionContext(
            user_id="user-1",
            tenant_id="tenant-1",
            request_id="request-1",
            correlation_id="corr-1",
        ),
        max_tokens=512,
    )
    decision = ExecutionDecision(
        topology=ExecutionTopology.REASONING,
        reasoning_depth="deep",
        reasoning_modes=["soft_exploration"],
        max_steps=4,
        max_model_calls=30,
        policy_decision_id="policy-1",
    )

    plan = runtime._build_authorized_plan(request, decision)

    assert plan.topology is ExecutionTopology.REASONING
    assert plan.reasoning_modes == ["soft_exploration"]
    assert plan.budget.max_reasoning_steps == 4
    assert plan.budget.max_model_calls == 30
    assert plan.budget.max_output_tokens == 512
    assert "deep" not in plan.reasoning_modes


def test_chat_runtime_does_not_translate_capabilities_into_reasoning_modes() -> None:
    runtime = ChatRuntime.__new__(ChatRuntime)
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "verify this"}],
        context=ChatExecutionContext(
            user_id="user-1",
            tenant_id="tenant-1",
            request_id="request-2",
            correlation_id="corr-2",
        ),
    )
    decision = ExecutionDecision(
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["verification"],
        required_capabilities=["web", "structured_output"],
        max_model_calls=7,
        policy_decision_id="policy-2",
    )

    plan = runtime._build_authorized_plan(request, decision)

    assert plan.reasoning_modes == ["verification"]
    assert plan.allowed_capabilities == ["web", "structured_output"]
