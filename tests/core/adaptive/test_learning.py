"""Tests for adaptive learning."""

from __future__ import annotations

import math
import pytest

from ai_karen_engine.core.adaptive.contracts import ActionOutcomeObservation
from ai_karen_engine.core.adaptive.learning.aggregates import EvidenceAggregator
from ai_karen_engine.core.adaptive.learning.contextual_policy import (
    BaselinePolicy,
    LinearContextualPolicy,
)
from ai_karen_engine.core.adaptive.learning.policy_contracts import (
    ActionRiskClass,
    DecisionType,
    PolicyContext,
)
from ai_karen_engine.core.adaptive.learning.observations import (
    AdaptiveObservationProcessor,
)
from ai_karen_engine.core.adaptive.learning.offline_evaluation import (
    OfflinePolicyEvaluator,
)
from ai_karen_engine.core.runtime.outcome.contracts import (
    ExecutionOutcome,
    ExecutionStatus,
    OutcomeRecord,
    UserOutcome,
)


class MockTaskSignature:
    def __init__(self):
        pass


def test_adaptive_observation_processor():
    processor = AdaptiveObservationProcessor()
    outcome = OutcomeRecord(
        outcome_id="out1",
        trajectory_id="traj1",
        tenant_id="t1",
        user_id="u1",
        execution_outcome=ExecutionOutcome(
            status=ExecutionStatus.SUCCESS,
            latency_ms=100.0,
            tool_success=True,
            response_completed=True,
        ),
        user_outcome=UserOutcome(
            feedback_type=None,
        ),
        metadata={"action_type": "use_tool", "target_id": "github"},
    )
    observation = processor.process_outcome(outcome)
    assert observation is not None
    assert observation.action_type == "use_tool"
    assert observation.target_id == "github"


def test_evidence_aggregator():
    aggregator = EvidenceAggregator()
    obs = ActionOutcomeObservation(
        observation_id="obs1",
        source_outcome_id="out1",
        action_type="use_tool",
        target_id="github",
        execution_status="success",
        latency_ms=100.0,
    )
    aggregator.add_observation(obs)
    profile = aggregator.get_capability_profile("github")
    assert profile.sample_count == 1
    assert profile.success_rate > 0.0


def test_contextual_policy_shadow():
    policy = LinearContextualPolicy()
    context = PolicyContext(
        feature_snapshot_id="snap-1",
        decision_type=DecisionType.RESPOND_STRATEGY,
        eligible_actions=["respond_directly", "ask_clarification"],
        risk_class=ActionRiskClass.LOW,
    )
    decision = policy.score_actions(context, context.eligible_actions)
    assert decision.policy_id == "linear-contextual"
    assert decision.chosen_action in context.eligible_actions
    assert math.isclose(sum(decision.probabilities.values()), 1.0, abs_tol=1e-6)


def test_offline_policy_evaluator():
    evaluator = OfflinePolicyEvaluator()
    outcomes = [
        {"execution_status": "success"},
        {"execution_status": "success"},
        {"execution_status": "failure"},
    ]
    result = evaluator.evaluate(outcomes)
    assert result["sample_count"] == 3
    assert result["baseline_success_rate"] == pytest.approx(2 / 3, rel=1e-3)
