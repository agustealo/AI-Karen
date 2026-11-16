"""KCOG-01B1: adversarial acceptance for governed verification effort OPE.

All observations in this file are synthetic test fixtures. They do not
represent an evaluated improvement in Karen's real-world cognition.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.intelligence.ml.policy_evaluation.contracts import (
    ActionRiskClass,
    DecisionType,
    PolicyContext,
    PolicyObservation,
    VerificationAction,
)
from ai_karen_engine.core.intelligence.ml.verification_policy_evaluation import (
    evaluate_verification_effort_candidate,
)

TENANT = "tenant-verification"
DIRECT = VerificationAction.RESPOND_DIRECT.value
VERIFY = VerificationAction.VERIFY_THEN_RESPOND.value
ACTIONS = [DIRECT, VERIFY]
BASELINE = SimpleNamespace(policy_id="baseline-verifier", policy_version="v1")
CANDIDATE = SimpleNamespace(policy_id="shadow-verifier", policy_version="v1")


def observation(
    index: int,
    *,
    action: str = DIRECT,
    needed: bool = False,
) -> PolicyObservation:
    return PolicyObservation(
        observation_id=f"decision-{index}",
        context=PolicyContext(
            feature_snapshot_id=f"decision-features-{index}",
            decision_type=DecisionType.RESPOND_STRATEGY,
            eligible_actions=list(ACTIONS),
            tenant_scope=TENANT,
            risk_class=ActionRiskClass.LOW,
        ),
        eligible_actions=list(ACTIONS),
        chosen_action=action,
        behavior_policy_id=BASELINE.policy_id,
        behavior_policy_version=BASELINE.policy_version,
        behavior_probabilities={DIRECT: 0.5, VERIFY: 0.5},
        chosen_probability=0.5,
        reward=1.0 if action == VERIFY and needed else 0.6,
        utility_policy_version="independent-utility-v1",
        candidate_probabilities={DIRECT: 0.5, VERIFY: 0.5},
        candidate_policy_id=CANDIDATE.policy_id,
        candidate_policy_version=CANDIDATE.policy_version,
        metadata={
            "reward_evidence_type": "independent_test",
            "reward_evidence_ref": f"eval:reward:{index}",
            "verification_needed": needed,
            "verification_label_source": "independent_test",
            "verification_label_ref": f"eval:need:{index}",
        },
    )


def evaluate(rows, *, min_samples=100):
    return evaluate_verification_effort_candidate(
        rows,
        tenant_id=TENANT,
        baseline_policy=BASELINE,
        candidate_policy=CANDIDATE,
        min_samples=min_samples,
    )


def test_empty_and_insufficient_return_truthful_shadow_report() -> None:
    empty = evaluate([])
    assert empty["promotion_decision"] == "insufficient_evidence"
    assert empty["eligible_count"] == 0
    assert empty["policy_activated"] is False
    five = evaluate(
        [
            observation(0, action=VERIFY, needed=False),
            observation(1, action=VERIFY, needed=True),
            observation(2, action=DIRECT, needed=True),
            observation(3, action=DIRECT, needed=False),
            observation(4, action=DIRECT, needed=False),
        ]
    )
    assert five["promotion_decision"] == "insufficient_evidence"
    assert five["evaluation_mode"] == "shadow"
    rates = five["observed_descriptive_rates"]
    assert rates["logged_verification_rate"] == pytest.approx(2 / 5)
    assert rates["logged_unnecessary_verification_rate"] == pytest.approx(1 / 5)
    assert rates["logged_missed_verification_rate"] == pytest.approx(1 / 5)
    assert five["policy_activated"] is False


@pytest.mark.parametrize(
    "mutation, error",
    [
        (lambda x: setattr(x.context, "tenant_scope", "tenant-other"), PermissionError),
        (lambda x: setattr(x.context, "decision_type", DecisionType.MODEL_SELECTION), ValueError),
        (lambda x: setattr(x, "behavior_probabilities", {}), ValueError),
        (lambda x: setattr(x, "chosen_probability", 0.0), ValueError),
        (lambda x: setattr(x, "reward", float("nan")), ValueError),
        (lambda x: setattr(x, "chosen_action", "invented"), ValueError),
        (lambda x: setattr(x.context, "feature_snapshot_id", ""), ValueError),
        (lambda x: setattr(x, "candidate_policy_id", ""), ValueError),
        (lambda x: setattr(x, "candidate_probabilities", {DIRECT: float("nan"), VERIFY: 0.5}), ValueError),
        (lambda x: setattr(x, "utility_policy_version", ""), ValueError),
        (lambda x: x.metadata.pop("reward_evidence_ref"), ValueError),
        (lambda x: x.metadata.update(verification_needed="yes"), ValueError),
        (lambda x: x.metadata.update(verification_label_source="self_report"), ValueError),
        (lambda x: x.metadata.update(verification_label_ref="untrusted label !"), ValueError),
        (lambda x: setattr(x.context, "risk_class", ActionRiskClass.HIGH), ValueError),
        (lambda x: setattr(x.context, "risk_class", ActionRiskClass.FORBIDDEN), ValueError),
        (lambda x: setattr(x, "eligible_actions", [DIRECT]), ValueError),
    ],
)
def test_invalid_evidence_cannot_enter_off_policy_comparison(mutation, error) -> None:
    entry = observation(1)
    mutation(entry)
    with pytest.raises(error):
        evaluate([entry])


def test_duplicate_decision_reward_or_verification_label_ref_rejected() -> None:
    first = observation(1)
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate([first, first])

    second = observation(2)
    second.metadata["reward_evidence_ref"] = first.metadata["reward_evidence_ref"]
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate([first, second])

    second = observation(2)
    second.metadata["verification_label_ref"] = first.metadata["verification_label_ref"]
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate([first, second])

    second = observation(2)
    second.metadata["verification_label_ref"] = second.metadata["reward_evidence_ref"]
    with pytest.raises(ValueError, match="distinct evidence receipts"):
        evaluate([second])




def test_missing_real_behavior_provenance_never_assumed_from_candidate() -> None:
    entry = observation(3)
    entry.behavior_probabilities = {DIRECT: 1.0, VERIFY: 0.0}
    with pytest.raises(ValueError, match="propensity"):
        evaluate([entry])

    entry = observation(4)
    entry.candidate_probabilities = {}
    with pytest.raises(ValueError, match="action distributions"):
        evaluate([entry])


def test_default_tenant_and_insufficient_minimum_fail_closed() -> None:
    for tenant in ("", "default"):
        with pytest.raises(ValueError, match="tenant"):
            evaluate_verification_effort_candidate(
                [],
                tenant_id=tenant,
                baseline_policy=BASELINE,
                candidate_policy=CANDIDATE,
            )
    for limit in (0, 99, True):
        with pytest.raises(ValueError, match="at least 100"):
            evaluate([], min_samples=limit)


def test_attested_shadow_evidence_delegates_to_existing_ope(monkeypatch) -> None:
    import ai_karen_engine.core.intelligence.ml.verification_policy_evaluation as module

    calls = []

    class ExistingOPE:
        def __init__(self, *, baseline_policy, ope_min_samples):
            assert baseline_policy is BASELINE
            assert ope_min_samples == 100

        def evaluate(self, observations, *, candidate_policy):
            assert candidate_policy is CANDIDATE
            calls.append(observations)
            return {
                "evaluation_id": "governed-ope-receipt",
                "promotion_decision": "promotion_blocked",
                "reason_codes": ["poor_overlap"],
                "estimates": {"ips": {"sample_count": 100}},
                "overlap_diagnostics": {"is_supported": False},
                "segment_metrics": {},
                "drift_status": "none",
            }

    monkeypatch.setattr(module, "OfflinePolicyEvaluator", ExistingOPE)
    rows = [
        observation(i, action=VERIFY if i % 2 else DIRECT, needed=bool(i % 4))
        for i in range(100)
    ]
    result = evaluate(rows)
    assert len(calls) == 1
    assert len(calls[0]) == 100
    assert result["policy_version"] == "kcog_verification_effort_ope_v1"
    assert result["evaluation_mode"] == "shadow"
    assert result["policy_activated"] is False
    assert result["runtime_policy_approval_required"] is True
    assert result["promotion_decision"] == "promotion_blocked"
    assert result["reason_codes"] == ["poor_overlap"]


def test_model_policy_regression_still_uses_shared_evidence_validator() -> None:
    from ai_karen_engine.core.intelligence.ml.policy_evaluation.validation import (
        validate_evaluated_policy_observations,
    )
    model = observation(1)
    model.context.decision_type = DecisionType.MODEL_SELECTION
    model.eligible_actions = ["model-a", "model-b"]
    model.context.eligible_actions = list(model.eligible_actions)
    model.chosen_action = "model-a"
    model.behavior_probabilities = {"model-a": 0.5, "model-b": 0.5}
    model.candidate_probabilities = dict(model.behavior_probabilities)
    validate_evaluated_policy_observations(
        [model],
        tenant_id=TENANT,
        decision_type=DecisionType.MODEL_SELECTION,
        domain="model",
    )
