"""KCOG-01B2: canonical OPE diagnostics cannot invent support or reward models.

All data here are synthetic fixtures; no production policy improvement is
inferred and runtime authorization is never exercised.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
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
from ai_karen_engine.core.intelligence.ml.policy_evaluation.estimators import (
    DoublyRobustEstimator,
    OPEIneligibleError,
    _effective_sample_size,
    compute_overlap_diagnostics,
)

ACTIONS = ["respond_direct", "verify_then_respond"]


def observed(
    idx: int,
    *,
    chosen: str = "respond_direct",
    reward: float = 0.1,
    candidate_direct: float = 0.25,
) -> PolicyObservation:
    candidate = {
        ACTIONS[0]: candidate_direct,
        ACTIONS[1]: 1.0 - candidate_direct,
    }
    return PolicyObservation(
        observation_id=f"obs-{idx}",
        context=PolicyContext(
            feature_snapshot_id=f"snapshot-{idx}",
            decision_type=DecisionType.RESPOND_STRATEGY,
            eligible_actions=list(ACTIONS),
            tenant_scope="tenant-1",
        ),
        eligible_actions=list(ACTIONS),
        chosen_action=chosen,
        behavior_policy_id="baseline-v1",
        behavior_policy_version="v1",
        behavior_probabilities={ACTIONS[0]: 0.5, ACTIONS[1]: 0.5},
        chosen_probability=0.5,
        candidate_probabilities=candidate,
        candidate_policy_id="shadow-v1",
        candidate_policy_version="v1",
        reward=reward,
    )


class ActionConditionedRewardModel:
    def predict_reward(self, context, action):
        assert context.feature_snapshot_id
        return {ACTIONS[0]: 0.2, ACTIONS[1]: 0.8}[action]


def test_kish_ess_exact_and_bounded() -> None:
    assert _effective_sample_size(np.array([])) == 0
    assert _effective_sample_size(np.array([1.0])) == pytest.approx(1.0)
    assert _effective_sample_size(np.ones(100)) == pytest.approx(100)
    assert _effective_sample_size(np.array([0.5, 1.5])) == pytest.approx(1.6)
    assert _effective_sample_size(np.array([0.0, 2.0])) == pytest.approx(1.0)
    assert _effective_sample_size(np.array([0.0, 0.0])) == 0
    assert _effective_sample_size(np.array([1.0, float("nan")])) == 0
    assert _effective_sample_size(np.array([-1.0, 2.0])) == 0


def test_overlap_requires_observed_support_not_just_eligible_action_list() -> None:
    only_direct = [observed(i) for i in range(100)]
    report = compute_overlap_diagnostics(only_direct, None, 100.0)
    assert report.is_supported is False
    assert report.action_support == {"respond_direct": 100}
    assert report.unsupported_actions == ["verify_then_respond"]
    assert report.coverage == pytest.approx(0.5)
    assert report.effective_sample_size == pytest.approx(100.0)

    both = [observed(0), observed(1, chosen=ACTIONS[1], reward=0.9)]
    supported = compute_overlap_diagnostics(both, None, 100.0)
    assert supported.is_supported is True
    assert supported.action_support == {
        "respond_direct": 1, "verify_then_respond": 1,
    }
    assert supported.unsupported_actions == []
    assert supported.coverage == pytest.approx(1.0)
    assert supported.effective_sample_size == pytest.approx(1.6)


def test_missing_reward_model_is_not_fake_doubly_robust_evidence() -> None:
    with pytest.raises(OPEIneligibleError, match="reward model"):
        DoublyRobustEstimator().estimate([observed(1)], None)


def test_real_action_conditioned_dr_includes_candidate_expected_outcomes() -> None:
    outcomes = [
        observed(1, chosen=ACTIONS[0], reward=0.1),
        observed(2, chosen=ACTIONS[1], reward=0.9),
    ]
    estimator = DoublyRobustEstimator(
        reward_model=ActionConditionedRewardModel()
    )
    report = estimator.estimate(outcomes, None)
    # E_pi Q(x,a)=0.25*0.2+0.75*0.8=0.65.
    # Direct chosen: 0.65 + 0.5 * (0.1-0.2) = 0.60.
    # Verify chosen: 0.65 + 1.5 * (0.9-0.8) = 0.80.
    assert report.estimate == pytest.approx(0.70)
    assert report.effective_sample_size == pytest.approx(1.6)
    assert report.sample_count == 2


@pytest.mark.parametrize("prediction", [float("nan"), float("inf"), -0.1, 1.1, True])
def test_invalid_reward_predictions_fail_closed(prediction) -> None:
    class BadModel:
        def predict_reward(self, context, action):
            return prediction

    with pytest.raises(OPEIneligibleError, match="finite"):
        DoublyRobustEstimator(reward_model=BadModel()).estimate(
            [observed(1)], None
        )


def test_model_failure_is_not_masked_by_observed_reward() -> None:
    class ExplodingModel:
        def predict_reward(self, context, action):
            raise RuntimeError("internal upstream")

    with pytest.raises(OPEIneligibleError, match="failed"):
        DoublyRobustEstimator(
            reward_model=ExplodingModel()
        ).estimate([observed(1)], None)


def test_default_offline_evaluation_cannot_claim_candidate_promotion() -> None:
    # We cannot claim a DR estimate from logged rewards alone, even if
    # both arms appear in the observational corpus.
    observations = [
        observed(i, chosen=ACTIONS[i % 2], reward=(i % 2) * 0.9)
        for i in range(120)
    ]
    evaluator = OfflinePolicyEvaluator(
        baseline_policy=SimpleNamespace(
            policy_id="baseline-v1", policy_version="v1"
        ),
    )
    report = evaluator.evaluate(
        observations,
        candidate_policy=SimpleNamespace(
            policy_id="shadow-v1", policy_version="v1",
        ),
    )
    assert "dr" not in report["estimates"]
    assert "ips" in report["estimates"]
    assert "snips" in report["estimates"]
    assert report["promotion_decision"] == PromotionDecision.PROMOTION_BLOCKED.value
    assert PromotionDecision.PROMOTION_ELIGIBLE.value != report["promotion_decision"]
    assert "insufficient_evidence" in report["reason_codes"]
