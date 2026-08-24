"""Tests for adaptive learning phase 3."""

from __future__ import annotations

import math
import random

import numpy as np
import pytest

from ai_karen_engine.core.adaptive.learning.contextual_policy import (
    BaselinePolicy,
    LinearContextualPolicy,
)
from ai_karen_engine.core.adaptive.learning.estimators import (
    DoublyRobustEstimator,
    IPSEstimator,
    OPEIneligibleError,
    SNIPSEstimator,
    compute_overlap_diagnostics,
)
from ai_karen_engine.core.adaptive.learning.policy_contracts import (
    ActionRiskClass,
    DecisionType,
    OPEIneligibilityReason,
    OverlapDiagnostics,
    PolicyContext,
    PolicyDecision,
    PolicyObservation,
    PolicyStatus,
    PromotionBlockReason,
    PromotionDecision,
    UtilityComponents,
    UtilityPolicy,
    validate_probability_distribution,
)
from ai_karen_engine.core.adaptive.learning.promotion import (
    PromotionConfig,
    PromotionEvidence,
    PolicyPromotionDecision,
    evaluate_promotion,
)
from ai_karen_engine.core.adaptive.learning.registry import PolicyRegistry, PolicyRecord
from ai_karen_engine.core.adaptive.learning.utility import (
    RawOutcomeRecord,
    compute_scalar_utility,
    compute_utility_components,
    derive_utility_record,
    is_utility_valid,
)


def _make_context(action="respond_directly", risk="low") -> PolicyContext:
    return PolicyContext(
        feature_snapshot_id="snap-1",
        decision_type=DecisionType.RESPOND_STRATEGY,
        eligible_actions=[action, "ask_clarification"],
        risk_class=ActionRiskClass.LOW,
    )


def _make_obs(action="respond_directly", reward=0.8, candidate_prob=None) -> PolicyObservation:
    context = _make_context(action)
    b_prob = {action: 0.7, "ask_clarification": 0.3}
    c_prob = candidate_prob if candidate_prob else {action: 0.9, "ask_clarification": 0.1}
    return PolicyObservation(
        observation_id=f"obs-{random.randint(1000, 9999)}",
        context=context,
        eligible_actions=[action, "ask_clarification"],
        chosen_action=action,
        behavior_policy_id="baseline",
        behavior_policy_version="v1",
        behavior_probabilities=b_prob,
        chosen_probability=0.7,
        reward=reward,
        candidate_probabilities=c_prob,
        candidate_policy_id="candidate",
        candidate_policy_version="v1",
    )


def test_validate_probability_distribution_valid():
    probs = {"a": 0.7, "b": 0.3}
    assert validate_probability_distribution(probs, ["a", "b"]) is None


def test_validate_probability_distribution_missing_action():
    probs = {"a": 0.7}
    err = validate_probability_distribution(probs, ["a", "b"])
    assert err is not None


def test_validate_probability_distribution_negative():
    probs = {"a": -0.1, "b": 1.1}
    err = validate_probability_distribution(probs, ["a", "b"])
    assert err is not None


def test_baseline_policy_deterministic():
    policy = BaselinePolicy()
    ctx = _make_context()
    decision = policy.score_actions(ctx, ctx.eligible_actions)
    assert decision.policy_id == "baseline"
    assert decision.exploration_used is False
    assert decision.chosen_action in ctx.eligible_actions
    assert math.isclose(sum(decision.probabilities.values()), 1.0, abs_tol=1e-6)


def test_linear_contextual_policy_shadow():
    policy = LinearContextualPolicy(mode=PolicyStatus.SHADOW)
    ctx = _make_context()
    decision = policy.score_actions(ctx, ctx.eligible_actions)
    assert decision.policy_id == "linear-contextual"
    assert decision.exploration_used is False
    assert decision.chosen_action in ctx.eligible_actions


def test_ips_estimator_known_synthetic():
    observations = [_make_obs(reward=1.0, candidate_prob={"respond_directly": 0.9, "ask_clarification": 0.1}) for _ in range(100)]
    estimator = IPSEstimator(max_importance_weight=100.0)
    est = estimator.estimate(observations, LinearContextualPolicy())
    assert est.estimator_name == "ips"
    assert est.sample_count == 100
    assert est.estimate > 0.0


def test_ips_zero_propensity_rejected():
    obs = _make_obs(candidate_prob={"respond_directly": 0.0, "ask_clarification": 0.1})
    estimator = IPSEstimator()
    with pytest.raises(OPEIneligibleError):
        estimator.estimate([obs], LinearContextualPolicy())


def test_snips_normalization():
    observations = [_make_obs(reward=1.0, candidate_prob={"respond_directly": 0.8, "ask_clarification": 0.2}) for _ in range(50)]
    estimator = SNIPSEstimator(max_importance_weight=100.0)
    est = estimator.estimate(observations, LinearContextualPolicy())
    assert est.estimator_name == "snips"
    assert est.sample_count == 50


def test_dr_estimator():
    observations = [_make_obs(reward=1.0, candidate_prob={"respond_directly": 0.9, "ask_clarification": 0.1}) for _ in range(50)]
    class SimpleModel:
        def predict(self, X):
            return np.full(X.shape[0], 0.5)
    estimator = DoublyRobustEstimator(reward_model=SimpleModel())
    est = estimator.estimate(observations, LinearContextualPolicy())
    assert est.estimator_name == "dr"


def test_utility_safety_violation():
    outcome = RawOutcomeRecord(outcome_id="o1", execution_status="success", safety_violation=True)
    components = compute_utility_components(outcome, UtilityPolicy())
    assert components.safety_penalty == 1.0
    assert not is_utility_valid(components)


def test_utility_versioned():
    policy = UtilityPolicy(utility_policy_version="v1")
    outcome = RawOutcomeRecord(outcome_id="o1", execution_status="success", quality_score=0.9)
    record = derive_utility_record(outcome, policy)
    assert record.utility_policy_version == "v1"


def test_promotion_insufficient_samples():
    evidence = PromotionEvidence(
        evaluation_id="e1",
        policy_id="p1",
        policy_version="v1",
        baseline_policy_id="baseline",
        baseline_policy_version="v1",
        sample_count=10,
    )
    decision = evaluate_promotion(evidence, PromotionConfig(min_samples=100))
    assert decision.decision == PromotionDecision.PROMOTION_BLOCKED
    assert PromotionBlockReason.INSUFFICIENT_SAMPLES in decision.reason_codes


def test_registry_promotion_rollback():
    registry = PolicyRegistry()
    registry.register(PolicyRecord(policy_id="p1", policy_version="v1", status=PolicyStatus.SHADOW))
    registry.set_alias("active", "p1", "v1")
    event = registry.promote("p1", "v1")
    assert event["action"] == "promote"
    active = registry.get_active_policy("p1")
    assert active.status == PolicyStatus.ACTIVE
