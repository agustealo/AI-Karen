"""KCOG-01C0: probabilities must describe the actually selected action rule.

Scores are never propensities. These test fixtures assert real deterministic
argmax policy semantics and preserve the no-offline-backfill boundary.
"""

from __future__ import annotations

import pytest

from ai_karen_engine.core.adaptive.learning.contextual_policy import (
    BaselinePolicy,
    LinearContextualPolicy,
)
from ai_karen_engine.core.intelligence.ml.policy_evaluation.contracts import (
    ActionRiskClass,
    DecisionType,
    PolicyContext,
    PolicyStatus,
    validate_probability_distribution,
)

_ACTIONS = ["respond_direct", "verify_then_respond"]


def _context(**features: float) -> PolicyContext:
    return PolicyContext(
        feature_snapshot_id="decision-time-snapshot",
        decision_type=DecisionType.RESPOND_STRATEGY,
        eligible_actions=list(_ACTIONS),
        normalized_features=dict(features),
        risk_class=ActionRiskClass.LOW,
        tenant_scope="tenant-observed",
    )


@pytest.mark.parametrize(
    "policy,features,expected",
    [
        (
            BaselinePolicy(),
            {"baseline:respond_direct": 0.2,
             "baseline:verify_then_respond": 0.9},
            "verify_then_respond",
        ),
        (
            BaselinePolicy(),
            {"baseline:respond_direct": 0.9,
             "baseline:verify_then_respond": 0.2},
            "respond_direct",
        ),
        (
            LinearContextualPolicy(
                weights={
                    "signal:verify_then_respond": 0.8,
                    "signal:respond_direct": 0.2,
                },
                mode=PolicyStatus.SHADOW,
            ),
            {"signal": 1.0},
            "verify_then_respond",
        ),
        (
            LinearContextualPolicy(
                weights={
                    "bias:verify_then_respond": 0.6,
                    "bias:respond_direct": 0.9,
                },
                mode=PolicyStatus.SHADOW,
            ),
            {},
            "respond_direct",
        ),
    ],
)
def test_deterministic_argmax_is_one_hot_not_normalized_score(
    policy, features, expected,
) -> None:
    decision = policy.score_actions(_context(**features), list(_ACTIONS))
    assert decision.chosen_action == expected
    assert decision.chosen_probability == 1.0
    assert decision.probabilities == {
        action: 1.0 if action == expected else 0.0
        for action in _ACTIONS
    }
    assert validate_probability_distribution(
        decision.probabilities, _ACTIONS,
    ) is None
    assert decision.exploration_used is False
    assert decision.metadata["selection_rule"] == "deterministic_argmax"
    assert decision.metadata["has_randomized_overlap"] is False
    assert any(score != decision.probabilities[action]
               for action, score in decision.scores.items())


def test_empty_eligible_actions_never_get_phantom_propensities() -> None:
    for policy in (BaselinePolicy(), LinearContextualPolicy()):
        decision = policy.score_actions(_context(), [])
        assert decision.chosen_action == ""
        assert decision.chosen_probability == 0.0
        assert decision.probabilities == {}


def test_linear_policy_tie_is_deterministic_not_uniform_randomization() -> None:
    policy = LinearContextualPolicy(mode=PolicyStatus.SHADOW)
    for _ in range(3):
        decision = policy.score_actions(_context(), list(_ACTIONS))
        assert decision.chosen_action == "respond_direct"
        assert decision.probabilities == {
            "respond_direct": 1.0,
            "verify_then_respond": 0.0,
        }
        assert decision.chosen_probability == 1.0
        assert decision.exploration_used is False


def test_scoring_does_not_change_shadow_policy_status() -> None:
    policy = LinearContextualPolicy(mode=PolicyStatus.SHADOW)
    first = policy.score_actions(_context(), list(_ACTIONS))
    assert first.metadata["has_randomized_overlap"] is False
    assert policy.status == PolicyStatus.SHADOW
