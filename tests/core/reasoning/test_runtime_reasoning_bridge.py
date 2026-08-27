from __future__ import annotations

from dataclasses import dataclass

import pytest

from ai_karen_engine.core.reasoning.strategy import ReasoningStrategyEngine
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionTopology,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.reasoning_bridge import (
    ReasoningActivationError,
    RuntimeReasoningBridge,
)


class DummySoftStrategy(ReasoningStrategyEngine):
    strategy_id = "soft_exploration"
    capabilities = ["soft_exploration"]
    supports_model_calls = True

    async def execute(self, request, context, evidence, budget):  # pragma: no cover
        raise AssertionError("activation tests do not execute the strategy")


@dataclass
class DummyComposed:
    strategy: ReasoningStrategyEngine
    prepared_prompt: str = "prepared\n<|soft_reasoning|>"
    prompt_version: str = "v1.0.0"
    provider_id: str = "builtin_transformers"
    model_id: str = "local-model"
    runtime_engine: str = "transformers:first_token_embedding_hook:v2"
    marker_token: str = "<|soft_reasoning|>"
    marker_token_id: int = 42
    profile: str = "paper_2025"
    maximum_total_model_calls: int = 30


class DummyComposer:
    def compose_paper_2025(self, **kwargs):
        return DummyComposed(strategy=DummySoftStrategy())


def _decision(*, model_calls: int = 30) -> ExecutionDecision:
    return ExecutionDecision(
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["soft_exploration"],
        max_steps=4,
        max_model_calls=model_calls,
        policy_decision_id="policy-1",
    )


def _plan(*, model_calls: int = 30) -> AuthorizedExecutionPlan:
    return AuthorizedExecutionPlan(
        execution_id="exec-1",
        policy_decision_id="policy-1",
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["soft_exploration"],
        budget=ExecutionBudget(
            max_reasoning_steps=4,
            max_model_calls=model_calls,
        ),
    )


def test_soft_reasoning_activation_injects_runtime_composed_strategy(monkeypatch) -> None:
    import ai_karen_engine.core.runtime.reasoning_bridge as bridge_module

    monkeypatch.setattr(
        bridge_module,
        "get_runtime_soft_reasoning_composer",
        lambda: DummyComposer(),
    )

    activation = RuntimeReasoningBridge().activate(
        objective="Solve the problem",
        evidence=["evidence"],
        decision=_decision(),
        plan=_plan(),
        preferred_provider="builtin_transformers",
        preferred_model="local-model",
    )

    assert activation.reasoning_modes == ("soft_exploration",)
    assert activation.request_metadata["soft_reasoning_profile"] == "paper_2025"
    assert activation.request_metadata["soft_reasoning_prompt_version"] == "v1.0.0"
    assert activation.runtime_metadata["reasoning_activation"] == "runtime_composed"
    assert activation.runtime_metadata["soft_reasoning_provider"] == "builtin_transformers"
    assert activation.runtime_metadata["soft_reasoning_model"] == "local-model"
    assert any(
        strategy.strategy_id == "soft_exploration"
        for strategy in activation.executor._strategies
    )


def test_soft_reasoning_activation_fails_closed_when_budget_is_too_small(monkeypatch) -> None:
    import ai_karen_engine.core.runtime.reasoning_bridge as bridge_module

    monkeypatch.setattr(
        bridge_module,
        "get_runtime_soft_reasoning_composer",
        lambda: DummyComposer(),
    )

    with pytest.raises(
        ReasoningActivationError,
        match="requires a model-call budget of at least 30",
    ) as exc_info:
        RuntimeReasoningBridge().activate(
            objective="Solve the problem",
            evidence=[],
            decision=_decision(model_calls=10),
            plan=_plan(model_calls=10),
            preferred_provider=None,
            preferred_model=None,
        )

    assert exc_info.value.code == "soft_reasoning_model_budget_insufficient"


def test_reasoning_activation_rejects_mode_not_authorized_by_plan() -> None:
    decision = ExecutionDecision(
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["soft_exploration"],
        max_model_calls=30,
        policy_decision_id="policy-1",
    )
    plan = AuthorizedExecutionPlan(
        execution_id="exec-1",
        policy_decision_id="policy-1",
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["causal"],
        budget=ExecutionBudget(max_model_calls=30),
    )

    with pytest.raises(ReasoningActivationError) as exc_info:
        RuntimeReasoningBridge().activate(
            objective="Solve",
            evidence=[],
            decision=decision,
            plan=plan,
            preferred_provider=None,
            preferred_model=None,
        )

    assert exc_info.value.code == "reasoning_mode_not_authorized"


def test_execution_decision_keeps_reasoning_and_model_call_budgets_distinct() -> None:
    decision = _decision(model_calls=30)

    assert decision.max_steps == 4
    assert decision.max_model_calls == 30
