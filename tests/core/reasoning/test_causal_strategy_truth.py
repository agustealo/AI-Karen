"""KCOG-00A3: registered causal strategy never fabricates reasoning success."""

from __future__ import annotations

import pytest

from ai_karen_engine.core.reasoning.contracts import (
    ReasoningBudget,
    ReasoningDisposition,
    ReasoningErrorCode,
    ReasoningRequest,
    ReasoningStatus,
)
from ai_karen_engine.core.reasoning.defaults import (
    get_default_executor,
    get_default_strategies,
)
from ai_karen_engine.core.reasoning.strategies.causal_strategy import (
    CausalReasoner,
)
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionContext,
    ExecutionTopology,
)


def _request(mode: str) -> ReasoningRequest:
    return ReasoningRequest(
        request_id="req-causal",
        correlation_id="corr-causal",
        tenant_id="tenant-a",
        user_id="user-a",
        conversation_id="conv-a",
        objective="Why did outcome change?",
        reasoning_modes=[mode],
        evidence=[],
        constraints={},
        policy_decision_id="policy-a",
        budget=ReasoningBudget(
            max_reasoning_steps=5,
            max_model_calls=1,
            max_tool_requests=1,
            max_refinement_iterations=1,
            max_duration_ms=3000,
            max_input_tokens=500,
            max_output_tokens=500,
        ),
        metadata={},
    )


def _context() -> ExecutionContext:
    return ExecutionContext(
        request_id="req-causal",
        correlation_id="corr-causal",
        user_id="user-a",
        tenant_id="tenant-a",
        conversation_id="conv-a",
        policy_decision_id="policy-a",
    )


def _plan(mode: str) -> AuthorizedExecutionPlan:
    return AuthorizedExecutionPlan(
        execution_id="run-causal",
        policy_decision_id="policy-a",
        topology=ExecutionTopology.REASONING,
        allowed_capabilities=["reasoning"],
        reasoning_modes=[mode],
        budget=ExecutionBudget(
            max_duration_ms=3000,
            max_model_calls=1,
            max_reasoning_steps=3,
            max_tool_calls=1,
            max_input_tokens=500,
            max_output_tokens=500,
        ),
    )


@pytest.mark.asyncio
async def test_causal_strategy_returns_typed_abstention() -> None:
    strategy = CausalReasoner()
    request = _request("causal")

    result = await strategy.execute(
        request, _context(), [], request.budget,
    )

    assert result.status == ReasoningStatus.ABSTAINED.value
    assert result.disposition == ReasoningDisposition.ABSTAIN.value
    assert result.error_code == ReasoningErrorCode.STRATEGY_UNAVAILABLE.value
    assert result.hypotheses == []
    assert result.diagnostics["reason_code"] == "causal_identification_unavailable"
    assert result.diagnostics["model_calls"] == 0
    assert result.diagnostics["tool_requests"] == 0


@pytest.mark.asyncio
async def test_default_executor_propagates_causal_abstention() -> None:
    result = await get_default_executor().execute(
        _request("causal"), _plan("causal"), _context(),
    )

    assert result.status == ReasoningStatus.ABSTAINED.value
    assert result.disposition == ReasoningDisposition.ABSTAIN.value
    assert result.hypotheses == []
    assert "causal_identification_unavailable" in result.unknowns


@pytest.mark.asyncio
async def test_counterfactual_mode_cannot_report_synthetic_success() -> None:
    result = await get_default_executor().execute(
        _request("counterfactual"), _plan("counterfactual"), _context(),
    )

    assert result.status == ReasoningStatus.ABSTAINED.value
    assert result.hypotheses == []


def test_causal_strategy_does_not_claim_general_evidence_synthesis() -> None:
    strategies = get_default_strategies()
    causal = next(s for s in strategies if s.strategy_id == "causal")

    assert not causal.can_handle(["evidence_synthesis"])
    assert causal.can_handle(["causal", "counterfactual"])
