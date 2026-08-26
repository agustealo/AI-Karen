"""Behavioral tests for reasoning/runtime authority boundaries."""

from __future__ import annotations

import pytest

from ai_karen_engine.core.reasoning.contracts import (
    ReasoningAssessment,
    ReasoningBudget,
    ReasoningRequest,
    ReasoningResult,
)
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionRequirements,
    ExecutionTopology,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision


def _reasoning_request(*, modes: list[str]) -> ReasoningRequest:
    return ReasoningRequest(
        request_id="req-1",
        correlation_id="corr-1",
        tenant_id="tenant-1",
        user_id="user-1",
        conversation_id="conv-1",
        objective="Analyze the evidence",
        reasoning_modes=modes,
        evidence=[],
        constraints={},
        policy_decision_id="policy-1",
        budget=ReasoningBudget(),
        metadata={},
    )


def test_legacy_reasoning_capability_alias_is_contained_at_contract_boundary() -> None:
    request = _reasoning_request(modes=["reasoning"])
    assert request.reasoning_modes == ["evidence_synthesis"]


def test_arbitrary_provider_capability_cannot_become_reasoning_mode() -> None:
    with pytest.raises(ValueError, match="unsupported reasoning mode"):
        _reasoning_request(modes=["web"])


def test_known_strategy_aliases_normalize_to_semantic_modes() -> None:
    request = _reasoning_request(modes=["verify", "refine", "soft"])
    assert request.reasoning_modes == [
        "verification",
        "refinement",
        "soft_exploration",
    ]


def test_legacy_deep_plan_expands_to_canonical_reasoning_modes() -> None:
    plan = AuthorizedExecutionPlan(
        execution_id="exec-1",
        policy_decision_id="policy-1",
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["deep"],
    )
    assert plan.reasoning_modes == [
        "causal",
        "evidence_synthesis",
        "verification",
        "refinement",
        "metacognition",
    ]


def test_authorized_memory_write_bridge_preserves_legacy_persistence_path() -> None:
    decision = ExecutionDecision(
        memory_recall_required=False,
        memory_write_allowed=True,
    )
    assert decision.memory_recall_required is True
    assert "compat_memory_write_requires_recall" in decision.reason_codes


def test_execution_requirements_never_grant_memory_write_by_default() -> None:
    requirements = ExecutionRequirements(
        request_id="req-1",
        correlation_id="corr-1",
    )
    assert requirements.memory_write_allowed is False


def test_reasoning_result_summary_is_deprecated_view_of_conclusion() -> None:
    result = ReasoningResult(
        reasoning_id="reasoning-1",
        disposition="complete",
        conclusion="Canonical conclusion",
        hypotheses=[],
        evidence=[],
        assumptions=[],
        unknowns=[],
        contradictions=[],
        assessment=ReasoningAssessment(),
        evidence_needs=[],
        suggested_next_actions=[],
        status="completed",
    )
    assert result.summary == result.conclusion
