"""KCOG-01B6: OPE must never invent or mutate historical candidate evidence.

All observations here are synthetic fixtures. Tests concern evidence integrity,
not the correctness of any model or authorization of a runtime policy.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
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

ACTIONS = ["respond_direct", "verify_then_respond"]
BASELINE = SimpleNamespace(policy_id="baseline", policy_version="v1")


class MutableCandidate:
    policy_id = "shadow"
    policy_version = "v2"

    def __init__(self) -> None:
        self.scoring_calls = 0

    def score_actions(self, context, eligible_actions):
        self.scoring_calls += 1
        return SimpleNamespace(
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            probabilities={ACTIONS[0]: 0.05, ACTIONS[1]: 0.95},
        )


def recorded(index: int) -> PolicyObservation:
    chosen = ACTIONS[index % 2]
    return PolicyObservation(
        observation_id=f"decision-{index}",
        context=PolicyContext(
            feature_snapshot_id=f"features-{index}",
            decision_type=DecisionType.RESPOND_STRATEGY,
            tenant_scope="verified-tenant",
            eligible_actions=list(ACTIONS),
        ),
        eligible_actions=list(ACTIONS),
        chosen_action=chosen,
        behavior_policy_id="baseline",
        behavior_policy_version="v1",
        behavior_probabilities={ACTIONS[0]: 0.5, ACTIONS[1]: 0.5},
        chosen_probability=0.5,
        candidate_probabilities={ACTIONS[0]: 0.25, ACTIONS[1]: 0.75},
        candidate_policy_id="shadow",
        candidate_policy_version="v2",
        reward=float(index % 2),
    )


def evaluate(rows, candidate=None):
    proposed = candidate if candidate is not None else MutableCandidate()
    report = OfflinePolicyEvaluator(baseline_policy=BASELINE).evaluate(
        rows, candidate_policy=proposed,
    )
    return report, proposed


def assert_ineligible(report, code: str) -> None:
    assert report["promotion_decision"] == PromotionDecision.OPE_INELIGIBLE.value
    assert report["reason_codes"] == [code]
    assert report["eligible_count"] == 0
    assert report["estimates"] == {}
    assert report["overlap_diagnostics"] is None
    assert report["observed_success_rate"] is None
    assert report["candidate_success_rate"] is None
    assert report["rate_source"] == "rejected_unverified_policy_observations"


def test_missing_candidate_propensities_must_not_be_recreated_by_mutable_policy() -> None:
    observation = recorded(0)
    observation.candidate_probabilities = {}
    before = deepcopy(observation)
    report, candidate = evaluate([observation])
    assert_ineligible(report, "invalid_logged_policy_observation")
    assert candidate.scoring_calls == 0
    assert observation == before


def test_mixed_valid_and_missing_candidate_rows_reject_entire_cohort() -> None:
    rows = [recorded(index) for index in range(110)]
    rows[100].candidate_probabilities = {}
    before = deepcopy(rows)
    report, candidate = evaluate(rows)
    assert_ineligible(report, "invalid_logged_policy_observation")
    assert report["sample_count"] == 110
    assert rows == before
    assert candidate.scoring_calls == 0


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda row: setattr(row, "candidate_policy_version", "v3"), "candidate_policy_version_mismatch"),
        (lambda row: setattr(row, "candidate_policy_id", "different"), "candidate_policy_version_mismatch"),
        (lambda row: setattr(row.context, "feature_snapshot_id", ""), "decision_time_snapshot_missing"),
        (lambda row: setattr(row, "behavior_policy_version", ""), "behavior_policy_provenance_missing"),
        (lambda row: setattr(row, "candidate_probabilities", {ACTIONS[0]: 0.9, ACTIONS[1]: 0.9}), "invalid_logged_policy_observation"),
        (lambda row: setattr(row, "reward", float("nan")), "invalid_logged_policy_observation"),
        (lambda row: setattr(row, "chosen_probability", 0.9), "invalid_logged_policy_observation"),
    ],
)
def test_unpinned_or_fabricated_evidence_rejected_without_partial_estimates(mutate, reason) -> None:
    rows = [recorded(i) for i in range(110)]
    mutate(rows[-1])
    report, candidate = evaluate(rows)
    assert_ineligible(report, reason)
    assert candidate.scoring_calls == 0


def test_candidate_policy_object_must_have_matching_versioned_identity() -> None:
    report, _ = evaluate([recorded(1)], SimpleNamespace(policy_id="shadow", policy_version="v3"))
    assert_ineligible(report, "candidate_policy_version_mismatch")

    report, _ = evaluate([recorded(2)], SimpleNamespace())
    assert_ineligible(report, "candidate_policy_identity_missing")


def test_valid_frozen_rows_produce_real_estimates_without_rescoring_or_mutation() -> None:
    rows = [recorded(index) for index in range(120)]
    original = deepcopy(rows)
    report, candidate = evaluate(rows)
    assert candidate.scoring_calls == 0
    assert rows == original
    assert "ips" in report["estimates"]
    assert "snips" in report["estimates"]
    assert "baseline_ips" in report["estimates"]
    assert "baseline_snips" in report["estimates"]
    # A validated action-conditioned DR reward model has not been attached.
    assert "dr" not in report["estimates"]
    assert report["promotion_decision"] == PromotionDecision.PROMOTION_BLOCKED.value
    assert report["rate_source"] == "logged_behavior_policy_reward_threshold"


def test_legacy_execution_status_path_is_unmodified_and_never_promotes() -> None:
    report, candidate = evaluate([
        {"execution_status": "success"},
        {"execution_status": "failure"},
    ])
    assert candidate.scoring_calls == 0
    assert report["promotion_decision"] == PromotionDecision.INSUFFICIENT_EVIDENCE.value
    assert report["baseline_success_rate"] is None
    assert report["candidate_success_rate"] is None


def test_incomplete_evidence_still_returns_a_structured_failure_not_fake_success() -> None:
    incomplete = recorded(1)
    incomplete.candidate_probabilities.clear()
    evaluator = OfflinePolicyEvaluator(baseline_policy=BASELINE)
    receipt = evaluator.evaluate([incomplete], candidate_policy=MutableCandidate())
    assert evaluator.last_evaluation() == receipt
    assert receipt["policy_id"] == "shadow"
    assert receipt["policy_version"] == "v2"
    assert receipt["sample_count"] == 1
    assert receipt["reason_codes"] == ["invalid_logged_policy_observation"]
