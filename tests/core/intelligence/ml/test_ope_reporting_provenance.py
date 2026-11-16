"""KCOG-01B3: OPE reporting distinguishes observed rewards from potential policy value.

Synthetic fixtures here never demonstrate improved cognition or authorize
runtime policy changes. Rates are descriptive reward-threshold fractions.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.adaptive.learning.offline_evaluation import (
    OfflinePolicyEvaluator,
)
from ai_karen_engine.core.intelligence.ml.policy_evaluation.contracts import (
    DecisionType,
    PolicyContext,
    PolicyObservation,
    PromotionDecision,
)

BASELINE = SimpleNamespace(policy_id="current", policy_version="v2")
CANDIDATE = SimpleNamespace(policy_id="proposed", policy_version="v3")
ACTIONS = ["respond_direct", "verify_then_respond"]


def observation(
    idx: int,
    *,
    behavior_policy_id: str = "current",
    behavior_policy_version: str = "v2",
    reward: float = 1.0,
    chosen_action: str = "respond_direct",
) -> PolicyObservation:
    return PolicyObservation(
        observation_id=f"observed-{idx}",
        context=PolicyContext(
            feature_snapshot_id=f"snapshot-{idx}",
            decision_type=DecisionType.RESPOND_STRATEGY,
            tenant_scope="tenant-verified",
            eligible_actions=list(ACTIONS),
        ),
        eligible_actions=list(ACTIONS),
        chosen_action=chosen_action,
        behavior_policy_id=behavior_policy_id,
        behavior_policy_version=behavior_policy_version,
        behavior_probabilities={
            "respond_direct": 0.5,
            "verify_then_respond": 0.5,
        },
        chosen_probability=0.5,
        candidate_probabilities={
            "respond_direct": 0.5,
            "verify_then_respond": 0.5,
        },
        candidate_policy_id=CANDIDATE.policy_id,
        candidate_policy_version=CANDIDATE.policy_version,
        reward=reward,
    )


def evaluate(rows):
    return OfflinePolicyEvaluator(
        baseline_policy=BASELINE,
    ).evaluate(rows, candidate_policy=CANDIDATE)


def test_counterfactual_candidate_never_inherits_behavior_success() -> None:
    rows = [observation(i, reward=1.0) for i in range(10)]
    report = evaluate(rows)
    assert report["observed_success_rate"] == pytest.approx(1.0)
    assert report["baseline_success_rate"] == pytest.approx(1.0)
    assert report["candidate_success_rate"] is None
    assert report["candidate_observed_count"] == 0
    assert report["baseline_observed_count"] == 10
    assert report["rate_source"] == "logged_behavior_policy_reward_threshold"
    assert report["promotion_decision"] == PromotionDecision.PROMOTION_BLOCKED.value
    assert "dr" not in report["estimates"]


def test_policy_version_and_actual_behavior_cohorts_define_rates() -> None:
    rows = [
        observation(0, reward=1.0),
        observation(1, reward=0.0),
        observation(2, behavior_policy_id="proposed", behavior_policy_version="v3", reward=1.0),
        observation(3, behavior_policy_id="proposed", behavior_policy_version="v3", reward=1.0),
        observation(4, behavior_policy_id="proposed", behavior_policy_version="v3", reward=0.0),
        observation(5, behavior_policy_id="proposed", behavior_policy_version="v2", reward=1.0),
    ]
    report = evaluate(rows)
    assert report["sample_count"] == 6
    assert report["baseline_observed_count"] == 2
    assert report["candidate_observed_count"] == 3
    assert report["baseline_success_rate"] == pytest.approx(0.5)
    assert report["candidate_success_rate"] == pytest.approx(2 / 3)
    assert report["observed_success_rate"] == pytest.approx(4 / 6)
    assert report["rate_source"] == "logged_behavior_policy_reward_threshold"


def test_no_baseline_observations_never_claims_baseline_rate() -> None:
    report = evaluate([
        observation(
            0,
            behavior_policy_id="other-behavior",
            behavior_policy_version="v2",
            reward=1.0,
        ),
    ])
    assert report["baseline_success_rate"] is None
    assert report["candidate_success_rate"] is None
    assert report["observed_success_rate"] == pytest.approx(1.0)
    assert report["baseline_observed_count"] == 0
    assert report["candidate_observed_count"] == 0


def test_legacy_status_is_not_candidate_or_baseline_evidence() -> None:
    report = evaluate([
        {"execution_status": "success"},
        {"execution_status": "failure"},
        {"execution_status": "success"},
    ])
    assert report["observed_success_rate"] == pytest.approx(2 / 3)
    assert report["baseline_success_rate"] is None
    assert report["candidate_success_rate"] is None
    assert report["baseline_observed_count"] == 0
    assert report["candidate_observed_count"] == 0
    assert report["rate_source"] == "unattributed_legacy_execution_status"
    assert report["estimates"] == {}
    assert report["promotion_decision"] == "insufficient_evidence"


def test_response_completion_cannot_be_a_candidate_accuracy_receipt() -> None:
    rows = [
        observation(i, reward=1.0, chosen_action=ACTIONS[i % 2])
        for i in range(120)
    ]
    report = evaluate(rows)
    assert report["candidate_success_rate"] is None
    assert report["candidate_observed_count"] == 0
    assert report["baseline_observed_count"] == 120
    assert report["rate_source"] == "logged_behavior_policy_reward_threshold"
    assert report["promotion_decision"] == PromotionDecision.PROMOTION_BLOCKED.value


def test_empty_evaluation_reports_absent_not_zero_success() -> None:
    report = evaluate([])
    assert report["sample_count"] == 0
    assert report["observed_success_rate"] is None
    assert report["baseline_success_rate"] is None
    assert report["candidate_success_rate"] is None
    assert report["baseline_observed_count"] == 0
    assert report["candidate_observed_count"] == 0
    assert report["rate_source"] == "no_observations"
    assert report["promotion_decision"] == "insufficient_evidence"
