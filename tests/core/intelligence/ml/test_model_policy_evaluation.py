"""Promotion of learned model routing needs independent reward and OPE support.

Test observations here are deliberate fixtures, NOT live model results.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.intelligence.ml.model_policy_evaluation import (
    evaluate_model_routing_candidate,
)
from ai_karen_engine.core.intelligence.ml.policy_evaluation.contracts import (
    DecisionType, PolicyContext, PolicyObservation,
)


TENANT = "tenant-test-1"


def verified_observation(index: int) -> PolicyObservation:
    return PolicyObservation(
        observation_id=f"obs-{index}",
        context=PolicyContext(
            feature_snapshot_id=f"features-{index}",
            decision_type=DecisionType.MODEL_SELECTION,
            tenant_scope=TENANT,
            eligible_actions=["model-a", "model-b"],
        ),
        eligible_actions=["model-a", "model-b"],
        chosen_action="model-a",
        behavior_policy_id="registered-default",
        behavior_policy_version="v1",
        behavior_probabilities={"model-a": 0.5, "model-b": 0.5},
        chosen_probability=0.5,
        reward=1.0,
        candidate_probabilities={"model-a": 0.5, "model-b": 0.5},
        candidate_policy_id="learned-model-selection",
        candidate_policy_version="v1",
        metadata={
            "reward_evidence_type": "independent_test",
            "reward_evidence_ref": f"test-run-{index}",
        },
    )


def run(items):
    return evaluate_model_routing_candidate(
        items, tenant_id=TENANT,
        baseline_policy=SimpleNamespace(
            policy_id="registered-default", policy_version="v1",
        ),
        candidate_policy=SimpleNamespace(
            policy_id="learned-model-selection", policy_version="v1",
        ),
    )


def test_empty_and_insufficient_evidence_blocks_promotion():
    empty = run([])
    assert empty["promotion_decision"] == "insufficient_evidence"
    assert empty["eligible_count"] == 0

    small = run([verified_observation(i) for i in range(5)])
    assert small["promotion_decision"] == "insufficient_evidence"
    assert small["eligible_count"] == 5


def test_completed_model_response_without_independent_review_is_rejected():
    observed = verified_observation(1)
    observed.metadata = {"reported_success": True}
    with pytest.raises(ValueError, match="Independent evaluation"):
        run([observed])


def test_deterministic_model_selection_without_real_propensity_is_rejected():
    observed = verified_observation(1)
    observed.behavior_probabilities = {}
    with pytest.raises(ValueError, match="action distributions"):
        run([observed])

    observed = verified_observation(2)
    observed.chosen_probability = 1.0
    with pytest.raises(ValueError, match="propensity"):
        run([observed])


def test_cross_tenant_or_wrong_decision_type_is_rejected():
    observed = verified_observation(1)
    observed.context.tenant_scope = "other-tenant"
    with pytest.raises(PermissionError, match="Cross-tenant"):
        run([observed])

    observed = verified_observation(2)
    observed.context.decision_type = DecisionType.AGENT_SELECTION
    with pytest.raises(ValueError, match="Non-model"):
        run([observed])


def test_duplicate_evidence_not_counted_twice():
    observed = verified_observation(1)
    with pytest.raises(ValueError, match="Duplicate"):
        run([observed, observed])


def test_ineligible_model_or_nonfinite_reward_fails_closed():
    observed = verified_observation(1)
    observed.chosen_action = "model-not-authorized"
    with pytest.raises(ValueError, match="not in the eligible"):
        run([observed])
    observed = verified_observation(2)
    observed.reward = float("nan")
    with pytest.raises(ValueError, match="finite"):
        run([observed])


def test_genuine_typed_evidence_reaches_existing_ope_not_a_duplicate_estimator(
    monkeypatch,
):
    import ai_karen_engine.core.intelligence.ml.model_policy_evaluation as module

    captures = []

    class ExistingOfflineEvaluator:
        def __init__(self, *, baseline_policy, ope_min_samples):
            assert baseline_policy.policy_id == "registered-default"
            assert ope_min_samples == 100

        def evaluate(self, observations, *, candidate_policy):
            captures.append((observations, candidate_policy))
            return {
                "evaluation_id": "real-ope-call",
                "promotion_decision": "promotion_blocked",
                "reason_codes": ["poor_overlap"],
                "estimates": {"ips": {"effective_sample_size": 5}},
                "overlap_diagnostics": {"is_supported": False},
                "segment_metrics": {},
                "drift_status": "none",
            }

    monkeypatch.setattr(module, "OfflinePolicyEvaluator", ExistingOfflineEvaluator)
    rows = [verified_observation(i) for i in range(100)]
    result = run(rows)
    assert len(captures) == 1
    assert len(captures[0][0]) == 100
    assert result["policy_version"] == "model_operational_outcome_v1"
    assert result["promotion_decision"] == "promotion_blocked"
    assert result["policy_activated"] is False
    assert result["reason_codes"] == ["poor_overlap"]
