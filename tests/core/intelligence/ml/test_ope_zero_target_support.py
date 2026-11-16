"""KCOG-01B5: deterministic candidate policies require valid zero-weight OPE.

Synthetic fixtures only. OPE estimates never grant action authorization or
constitute independently verified real-world intelligence improvements.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from ai_karen_engine.core.intelligence.ml.policy_evaluation.contracts import (
    DecisionType,
    OverlapDiagnostics,
    PolicyContext,
    PolicyEstimate,
    PolicyObservation,
    PromotionDecision,
)
from ai_karen_engine.core.intelligence.ml.policy_evaluation.estimators import (
    DoublyRobustEstimator,
    IPSEstimator,
    OPEIneligibleError,
    SNIPSEstimator,
    compute_overlap_diagnostics,
    validate_observation,
)
from ai_karen_engine.core.intelligence.ml.policy_evaluation.promotion import (
    PromotionConfig,
    PromotionEvidence,
    evaluate_promotion,
)

ACTIONS = ["respond_direct", "verify_then_respond"]


def observed(index: int, *, chosen_action: str | None = None) -> PolicyObservation:
    chosen = chosen_action or ACTIONS[index % 2]
    return PolicyObservation(
        observation_id=f"logged-{index}",
        context=PolicyContext(
            feature_snapshot_id=f"features-{index}",
            decision_type=DecisionType.RESPOND_STRATEGY,
            tenant_scope="tenant-verified",
            eligible_actions=list(ACTIONS),
        ),
        eligible_actions=list(ACTIONS),
        chosen_action=chosen,
        behavior_policy_id="known-baseline",
        behavior_policy_version="v1",
        behavior_probabilities={ACTIONS[0]: 0.5, ACTIONS[1]: 0.5},
        chosen_probability=0.5,
        candidate_policy_id="deterministic-verifier",
        candidate_policy_version="v1",
        candidate_probabilities={ACTIONS[0]: 0.0, ACTIONS[1]: 1.0},
        reward=float(chosen == ACTIONS[1]),
    )


class IndependentlyFittedRewardFixture:
    def predict_reward(self, context, action):
        assert context.feature_snapshot_id.startswith("features-")
        return float(action == ACTIONS[1])


def test_zero_candidate_weight_is_valid_not_missing_propensity() -> None:
    direct = observed(0, chosen_action=ACTIONS[0])
    verify = observed(1, chosen_action=ACTIONS[1])
    assert validate_observation(direct) is None
    assert validate_observation(verify) is None
    assert direct.candidate_probabilities[direct.chosen_action] == 0.0


def test_deterministic_candidate_uses_zero_weight_rows_in_all_estimators() -> None:
    rows = [observed(index) for index in range(100)]
    estimates = [
        IPSEstimator().estimate(rows, None),
        SNIPSEstimator().estimate(rows, None),
        DoublyRobustEstimator(
            reward_model=IndependentlyFittedRewardFixture()
        ).estimate(rows, None),
    ]
    for report in estimates:
        assert report.estimate == pytest.approx(1.0)
        assert report.effective_sample_size == pytest.approx(50.0)
        assert report.sample_count == 100
        assert report.clipped_weight_count == 0
    overlap = compute_overlap_diagnostics(rows, None, 100)
    assert overlap.is_supported is True
    assert overlap.effective_sample_size == pytest.approx(50.0)
    assert overlap.unsupported_actions == []
    assert overlap.coverage == pytest.approx(1.0)


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (
            lambda r: replace(r, candidate_probabilities={ACTIONS[0]: 0.0, ACTIONS[1]: 0.0}),
            "invalid_candidate_distribution",
        ),
        (
            lambda r: replace(r, candidate_probabilities={ACTIONS[0]: -0.1, ACTIONS[1]: 1.1}),
            "invalid_candidate_distribution",
        ),
        (
            lambda r: replace(r, candidate_probabilities={ACTIONS[0]: 0.0}),
            "invalid_candidate_action_distribution",
        ),
        (
            lambda r: replace(r, candidate_probabilities={ACTIONS[0]: 0.0, ACTIONS[1]: 1.0, "unexpected": 0.0}),
            "invalid_candidate_action_distribution",
        ),
        (
            lambda r: replace(r, candidate_probabilities={ACTIONS[0]: False, ACTIONS[1]: 1.0}),
            "invalid_candidate_probability",
        ),
        (
            lambda r: replace(r, candidate_probabilities={ACTIONS[0]: 0.0, ACTIONS[1]: float("inf")}),
            "invalid_candidate_probability",
        ),
        (
            lambda r: replace(r, chosen_probability=1.0),
            "chosen_probability_mismatch",
        ),
        (
            lambda r: replace(r, reward=float("nan")),
            "invalid_reward",
        ),
    ],
)
def test_invalid_logged_distribution_never_passes_estimators(mutation, reason) -> None:
    bad = mutation(observed(0))
    assert reason in (validate_observation(bad) or "")
    with pytest.raises(OPEIneligibleError, match=reason):
        IPSEstimator().estimate([bad], None)
    with pytest.raises(OPEIneligibleError, match=reason):
        SNIPSEstimator().estimate([bad], None)


def test_unobserved_target_has_no_positive_overlap_or_snips_value() -> None:
    rows = [observed(index, chosen_action=ACTIONS[0]) for index in range(100)]
    overlap = compute_overlap_diagnostics(rows, None, 100)
    assert overlap.is_supported is False
    assert overlap.coverage == 0.0
    assert overlap.unsupported_actions == [ACTIONS[1]]
    assert overlap.effective_sample_size == 0.0
    with pytest.raises(OPEIneligibleError):
        SNIPSEstimator().estimate(rows, None)


def test_behavior_policy_zero_support_for_target_is_detected_per_context() -> None:
    first = observed(0)
    first.behavior_probabilities = {ACTIONS[0]: 1.0, ACTIONS[1]: 0.0}
    first.chosen_probability = 1.0
    assert validate_observation(first) is None
    overlap = compute_overlap_diagnostics([first, observed(1)], None, 100)
    assert overlap.is_supported is False
    assert ACTIONS[1] in overlap.unsupported_actions


def evidence_without_overlap() -> PromotionEvidence:
    def score(name: str, value: float, lower: float, upper: float) -> PolicyEstimate:
        return PolicyEstimate(
            estimator_name=name,
            estimate=value,
            lower_bound=lower,
            upper_bound=upper,
            confidence_level=0.95,
            sample_count=150,
            effective_sample_size=150.0,
        )

    return PromotionEvidence(
        evaluation_id="synthetic-only",
        policy_id="candidate",
        policy_version="v1",
        baseline_policy_id="baseline",
        baseline_policy_version="v1",
        estimates={
            "ips": score("ips", 0.90, 0.80, 0.98),
            "baseline_ips": score("baseline_ips", 0.40, 0.30, 0.50),
        },
        sample_count=150,
    )


def test_promotion_requires_positive_overlap_evidence_not_just_utility() -> None:
    report = evidence_without_overlap()
    config = PromotionConfig(require_dr=False, require_snips=False)
    missing = evaluate_promotion(report, config)
    assert missing.decision is PromotionDecision.PROMOTION_BLOCKED
    assert any("overlap diagnostics missing" in msg for msg in missing.messages)

    report.overlap_diagnostics = OverlapDiagnostics(
        effective_sample_size=0.0,
        minimum_propensity=0.5,
        maximum_importance_weight=1.0,
        coverage=1.0,
        action_support={ACTIONS[0]: 150},
        is_supported=True,
    )
    rejected = evaluate_promotion(report, config)
    assert rejected.decision is PromotionDecision.PROMOTION_BLOCKED
    assert "poor_overlap" in [reason.value for reason in rejected.reason_codes]

    report.overlap_diagnostics.effective_sample_size = 150.0
    accepted = evaluate_promotion(report, config)
    assert accepted.decision is PromotionDecision.PROMOTION_ELIGIBLE
    assert accepted.promotion_id is None
