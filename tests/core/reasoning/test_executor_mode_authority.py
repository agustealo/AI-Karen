from __future__ import annotations

from dataclasses import dataclass

import pytest

from ai_karen_engine.core.reasoning.contracts import (
    ReasoningAssessment,
    ReasoningBudget,
    ReasoningHypothesis,
    ReasoningRequest,
    ReasoningResult,
    ReasoningStatus,
)
from ai_karen_engine.core.reasoning.executor import ReasoningExecutor
from ai_karen_engine.core.reasoning.strategy import ReasoningStrategyEngine
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionContext,
    ExecutionTopology,
)


@dataclass
class RecordingStrategy(ReasoningStrategyEngine):
    strategy_id: str
    capabilities: list[str]
    supports_model_calls: bool = False
    supports_tools: bool = False
    calls: int = 0
    observed_model_budget: int | None = None

    async def execute(self, request, context, evidence, budget):
        self.calls += 1
        self.observed_model_budget = budget.max_model_calls
        return ReasoningResult(
            reasoning_id="",
            disposition="complete",
            conclusion=self.strategy_id,
            hypotheses=[
                ReasoningHypothesis(
                    hypothesis_id=f"{self.strategy_id}-1",
                    statement=self.strategy_id,
                    confidence=0.8,
                    provenance="test",
                )
            ],
            evidence=evidence,
            assumptions=[],
            unknowns=[],
            contradictions=[],
            assessment=ReasoningAssessment(confidence=0.8),
            evidence_needs=[],
            suggested_next_actions=[],
            status=ReasoningStatus.COMPLETED.value,
            diagnostics={
                "model_calls": 2 if self.supports_model_calls else 0,
                "tool_requests": 1 if self.supports_tools else 0,
            },
            memory_candidates=[],
        )


def make_request(*modes: str) -> ReasoningRequest:
    return ReasoningRequest(
        request_id="req-1",
        correlation_id="corr-1",
        tenant_id="tenant-a",
        user_id="user-a",
        conversation_id="conv-a",
        objective="evaluate",
        reasoning_modes=list(modes),
        evidence=[],
        constraints={},
        policy_decision_id="policy-1",
        budget=ReasoningBudget(
            max_reasoning_steps=5,
            max_model_calls=5,
            max_tool_requests=2,
            max_refinement_iterations=2,
            max_duration_ms=5000,
            max_input_tokens=1024,
            max_output_tokens=512,
        ),
        metadata={},
    )


def make_plan(*modes: str) -> AuthorizedExecutionPlan:
    return AuthorizedExecutionPlan(
        execution_id="exec-1",
        policy_decision_id="policy-1",
        topology=ExecutionTopology.REASONING,
        allowed_capabilities=["reasoning"],
        reasoning_modes=list(modes),
        budget=ExecutionBudget(
            max_duration_ms=4000,
            max_model_calls=3,
            max_reasoning_steps=4,
            max_tool_calls=1,
            max_input_tokens=900,
            max_output_tokens=400,
        ),
    )


def make_context() -> ExecutionContext:
    return ExecutionContext(
        request_id="req-1",
        correlation_id="corr-1",
        user_id="user-a",
        tenant_id="tenant-a",
        conversation_id="conv-a",
        policy_decision_id="policy-1",
    )


@pytest.mark.asyncio
async def test_executor_runs_only_requested_and_authorized_modes() -> None:
    causal = RecordingStrategy("causal-test", ["causal"])
    soft = RecordingStrategy("soft-test", ["soft_exploration"], supports_model_calls=True)
    verifier = RecordingStrategy("verify-test", ["verification"])
    executor = ReasoningExecutor([causal, soft, verifier])

    result = await executor.execute(
        make_request("soft_exploration"),
        make_plan("soft_exploration", "verification"),
        make_context(),
    )

    assert soft.calls == 1
    assert causal.calls == 0
    assert verifier.calls == 0
    assert result.diagnostics["strategies_executed"] == ["soft-test"]
    assert result.diagnostics["effective_reasoning_modes"] == ["soft_exploration"]


@pytest.mark.asyncio
async def test_executor_rejects_mode_not_authorized_by_runtime_policy() -> None:
    soft = RecordingStrategy("soft-test", ["soft_exploration"], supports_model_calls=True)
    executor = ReasoningExecutor([soft])

    result = await executor.execute(
        make_request("soft_exploration"),
        make_plan("verification"),
        make_context(),
    )

    assert soft.calls == 0
    assert result.error_code == "invalid_request"
    assert result.status == ReasoningStatus.FAILED.value
    assert "not authorized" in result.conclusion


@pytest.mark.asyncio
async def test_executor_uses_plan_modes_when_request_modes_are_empty() -> None:
    verifier = RecordingStrategy("verify-test", ["verification"])
    executor = ReasoningExecutor([verifier])

    result = await executor.execute(
        make_request(),
        make_plan("verification"),
        make_context(),
    )

    assert verifier.calls == 1
    assert result.diagnostics["effective_reasoning_modes"] == ["verification"]


@pytest.mark.asyncio
async def test_execution_budget_is_normalized_to_reasoning_budget() -> None:
    soft = RecordingStrategy("soft-test", ["soft_exploration"], supports_model_calls=True)
    executor = ReasoningExecutor([soft])

    result = await executor.execute(
        make_request("soft_exploration"),
        make_plan("soft_exploration"),
        make_context(),
    )

    assert result.status == ReasoningStatus.COMPLETED.value
    assert soft.observed_model_budget == 3
    assert result.diagnostics["model_calls"] == 2


@pytest.mark.asyncio
async def test_multiple_authorized_modes_execute_in_requested_order() -> None:
    verifier = RecordingStrategy("verify-test", ["verification"])
    refiner = RecordingStrategy("refine-test", ["refinement"])
    executor = ReasoningExecutor([refiner, verifier])

    result = await executor.execute(
        make_request("verification", "refinement"),
        make_plan("verification", "refinement"),
        make_context(),
    )

    assert verifier.calls == 1
    assert refiner.calls == 1
    assert result.diagnostics["strategies_executed"] == ["verify-test", "refine-test"]
