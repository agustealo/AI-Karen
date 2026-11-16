"""KCOG-01B4: policy promotion requires evidence of gain over the baseline.

These fixtures are synthetic. They test mathematical gates only and do not
establish causal improvement or authorize any production policy activation.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.adaptive.learning.offline_evaluation import (
    OfflinePolicyEvaluator,
)
from ai_karen_engine.core.intelligence.ml.policy_evaluation.contracts import (
    DecisionType,
    OverlapDiagnostics,
    PolicyContext,
    PolicyEstimate,
    PolicyObservation,
    PromotionDecision,
)
from ai_karen_engine.core.intelligence.ml.policy_evaluation.promotion import (
    PromotionConfig,
    PromotionEvidence,
    evaluate_promotion,
)

BASELINE = SimpleNamespace(policy_id="baseline-verified", policy_version="v2")
CANDIDATE = SimpleNamespace(policy_id="candidate-shadow", policy_version="v1")
ACTIONS = ["respond_direct", "verify_then_respond"]


def estimate(name: str, value: float, low: float, high: float, *, count: int = 150) -> PolicyEstimate:
    return PolicyEstimate(
        estimator_name=name,
        estimate=value,
        lower_bound=low,
        upper_bound=high,
        confidence_level=0.95,
        sample_count=count,
        effective_sample_size=float(count),
    )


def evidence() -> PromotionEvidence:
    estimates = {
        name: estimate(name, 0.82, 0.76, 0.88)
        for name in ("ips", "snips", "dr")
    }
    estimates.update({
        f"baseline_{name}": estimate(f"baseline_{name}", 0.60, 0.52, 0.68)
        for name in ("ips", "snips", "dr")
    })
    return PromotionEvidence(
        evaluation_id="shadow-eval-fixture",
        policy_id=CANDIDATE.policy_id,
        policy_version=CANDIDATE.policy_version,
        baseline_policy_id=BASELINE.policy_id,
        baseline_policy_version=BASELINE.policy_version,
        estimates=estimates,
        sample_count=150,
        overlap_diagnostics=OverlapDiagnostics(
            effective_sample_size=150.0,
            minimum_propensity=0.5,
            maximum_importance_weight=1.0,
            coverage=1.0,
            action_support={"respond_direct": 75, "verify_then_respond": 75},
            is_supported=True,
        ),
    )


def decision(data: PromotionEvidence):
    return evaluate_promotion(data, PromotionConfig())


def test_complete_strong_baseline_relative_evidence_reaches_eligibility_only() -> None:
    receipt = decision(evidence())
    assert receipt.decision is PromotionDecision.PROMOTION_ELIGIBLE
    assert receipt.promotion_id is None
    assert receipt.evidence is not None


def test_strong_absolute_candidate_value_without_baseline_is_blocked() -> None:
    data = evidence()
    data.estimates = {key: item for key, item in data.estimates.items() if not key.startswith("baseline_")}
    result = decision(data)
    assert result.decision is PromotionDecision.PROMOTION_BLOCKED
    assert "insufficient_evidence" in [r.value for r in result.reason_codes]
    assert any("baseline-relative estimate missing" in msg for msg in result.messages)


def test_missing_baseline_dr_blocks_even_with_ips_and_snips_comparison() -> None:
    data = evidence()
    del data.estimates["baseline_dr"]
    result = decision(data)
    assert result.decision is PromotionDecision.PROMOTION_BLOCKED
    assert any("dr baseline-relative estimate missing" in msg for msg in result.messages)


def test_positive_absolute_reward_but_not_positive_gain_is_blocked() -> None:
    data = evidence()
    for name in ("ips", "snips", "dr"):
        data.estimates[f"baseline_{name}"] = estimate(name, 0.80, 0.74, 0.86)
    result = decision(data)
    assert result.decision is PromotionDecision.PROMOTION_BLOCKED
    assert any("does not beat baseline" in msg for msg in result.messages)


def test_tie_and_minimum_gain_are_not_improvement() -> None:
    data = evidence()
    for name in ("ips", "snips", "dr"):
        data.estimates[name] = estimate(name, 0.82, 0.68, 0.88)
    assert decision(data).decision is PromotionDecision.PROMOTION_BLOCKED

    data = evidence()
    result = evaluate_promotion(data, PromotionConfig(min_gain=0.10))
    assert result.decision is PromotionDecision.PROMOTION_BLOCKED


@pytest.mark.parametrize(
    "mutation",
    [
        lambda estimate: replace(estimate, lower_bound=float("nan")),
        lambda estimate: replace(estimate, upper_bound=float("inf")),
        lambda estimate: replace(estimate, sample_count=100),
        lambda estimate: replace(estimate, effective_sample_size=0.0),
        lambda estimate: replace(estimate, confidence_level=0.90),
        lambda estimate: replace(estimate, lower_bound=0.90, upper_bound=0.70),
    ],
)
def test_invalid_baseline_confidence_and_sample_provenance_fail_closed(mutation) -> None:
    data = evidence()
    data.estimates["baseline_ips"] = mutation(data.estimates["baseline_ips"])
    result = decision(data)
    assert result.decision is PromotionDecision.PROMOTION_BLOCKED
    assert any("unverified or invalid" in msg for msg in result.messages)


def observation(index: int, *, behavior_id: str = "baseline-verified", behavior_version: str = "v2") -> PolicyObservation:
    chosen = ACTIONS[index % 2]
    return PolicyObservation(
        observation_id=f"evidence-{index}",
        context=PolicyContext(
            feature_snapshot_id=f"snapshot-{index}",
            decision_type=DecisionType.RESPOND_STRATEGY,
            tenant_scope="tenant-a",
            eligible_actions=list(ACTIONS),
        ),
        eligible_actions=list(ACTIONS),
        chosen_action=chosen,
        behavior_policy_id=behavior_id,
        behavior_policy_version=behavior_version,
        behavior_probabilities={ACTIONS[0]: 0.5, ACTIONS[1]: 0.5},
        chosen_probability=0.5,
        candidate_policy_id=CANDIDATE.policy_id,
        candidate_policy_version=CANDIDATE.policy_version,
        candidate_probabilities={ACTIONS[0]: 0.25, ACTIONS[1]: 0.75},
        reward=float(index % 3 != 0),
    )


def offline(rows):
    return OfflinePolicyEvaluator(baseline_policy=BASELINE).evaluate(
        rows, candidate_policy=CANDIDATE,
    )


def test_baseline_uses_logged_behavior_propensities_without_mutating_records() -> None:
    rows = [observation(i) for i in range(120)]
    before = [dict(o.candidate_probabilities) for o in rows]
    result = offline(rows)
    assert result["estimates"]["baseline_ips"]["sample_count"] == 120
    assert result["estimates"]["baseline_snips"]["sample_count"] == 120
    assert result["estimates"]["baseline_ips"]["estimate"] == pytest.approx(80 / 120)
    assert result["estimates"]["baseline_snips"]["estimate"] == pytest.approx(80 / 120)
    assert all(row.candidate_probabilities == before[i] for i, row in enumerate(rows))
    assert "baseline_dr" not in result["estimates"]
    assert result["promotion_decision"] == PromotionDecision.PROMOTION_BLOCKED.value


def test_mixed_behavior_policies_cannot_synthesize_missing_baseline_estimates() -> None:
    rows = [observation(i) for i in range(120)]
    rows[3] = observation(3, behavior_id="alternate-policy", behavior_version="v1")
    result = offline(rows)
    assert not any(k.startswith("baseline_") for k in result["estimates"])
    assert result["promotion_decision"] == PromotionDecision.PROMOTION_BLOCKED.value


def test_wrong_baseline_version_blocks_paired_baseline_evaluation() -> None:
    rows = [observation(i, behavior_version="v1") for i in range(120)]
    result = offline(rows)
    assert not any(k.startswith("baseline_") for k in result["estimates"])
    assert result["promotion_decision"] == PromotionDecision.PROMOTION_BLOCKED.value
