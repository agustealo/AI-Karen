from __future__ import annotations

from ai_karen_engine.core.cortex.behavior.contracts import (
    BehaviorDecision,
    BehaviorScoreComponents,
    BehaviorType,
    VerificationDepth,
    VerificationReason,
    VerificationRequirement,
)


def test_behavior_type_values():
    assert BehaviorType.RESPOND.value == "respond"
    assert BehaviorType.ABSTAIN.value == "abstain"


def test_behavior_score_utility_bounded():
    s = BehaviorScoreComponents(
        goal_alignment=1.0,
        belief_support=1.0,
        risk=0.8,
        interruption_cost=0.5,
    )
    assert 0.0 <= s.utility <= 1.0


def test_verification_requirement_creation():
    req = VerificationRequirement(
        required=True,
        reason=VerificationReason.HIGH_RISK,
        depth=VerificationDepth.DEEP,
    )
    assert req.required is True
    assert req.reason == VerificationReason.HIGH_RISK


def test_behavior_decision_abstain():
    decision = BehaviorDecision(
        decision_id="d1",
        selected_behavior=BehaviorType.ABSTAIN,
        reason_codes=["insufficient_evidence"],
    )
    assert decision.selected_behavior == BehaviorType.ABSTAIN
    assert "insufficient_evidence" in decision.reason_codes
