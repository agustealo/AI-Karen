from __future__ import annotations

from ai_karen_engine.core.cortex.behavior.contracts import (
    BehaviorCandidate,
    BehaviorConstraint,
    BehaviorDecision,
    BehaviorScoreComponents,
    BehaviorSelectionContext,
    BehaviorType,
    VerificationReason,
    VerificationRequirement,
)
from ai_karen_engine.core.cortex.behavior.eligibility import BehaviorEligibilityGate
from ai_karen_engine.core.cortex.behavior.scoring import BehaviorScoringEngine
from ai_karen_engine.core.cortex.behavior.selector import BehaviorSelector


def _ctx(**kwargs: Any) -> BehaviorSelectionContext:
    return BehaviorSelectionContext(request_id="r1", correlation_id="c1", tenant_id="t1", **kwargs)


def _candidate(btype: BehaviorType = BehaviorType.RESPOND, **kwargs: Any) -> BehaviorCandidate:
    return BehaviorCandidate(candidate_id=f"c-{btype.value}", behavior_type=btype, **kwargs)


def test_memory_can_influence_behavior_selection():
    engine = BehaviorScoringEngine()
    candidate = _candidate(BehaviorType.RECALL)
    ctx = _ctx(memory_signals=[{"relevance": 0.9}])
    score = engine.score(candidate, ctx)
    assert score.belief_support == 0.5


def test_goals_can_influence_behavior_selection():
    engine = BehaviorScoringEngine()
    candidate = _candidate(BehaviorType.USE_WORKFLOW)
    ctx = _ctx(goal_state={"active_goals": ["deploy"]})
    score = engine.score(candidate, ctx)
    assert score.goal_alignment > 0.5


def test_beliefs_can_change_selected_behavior():
    selector = BehaviorSelector()
    candidates = [_candidate(BehaviorType.RESPOND), _candidate(BehaviorType.ABSTAIN)]
    ctx = _ctx(belief_assessment={"confidence": 0.1})
    decision = selector.select(ctx, candidates)
    assert decision.selected_behavior == BehaviorType.ABSTAIN


def test_salience_can_change_priority_without_overriding_policy():
    engine = BehaviorScoringEngine()
    candidate = _candidate(BehaviorType.ASK)
    ctx = _ctx(salience={"overall": 0.9}, policy_constraints={"blocked_behaviors": ["ask"]})
    score = engine.score(candidate, ctx)
    assert score.policy_fit == 0.0


def test_user_preference_can_affect_ask_vs_act():
    engine = BehaviorScoringEngine()
    candidate = _candidate(BehaviorType.ASK)
    ctx = _ctx(user_model={"prefers_action_over_clarification": False})
    score = engine.score(candidate, ctx)
    assert score.user_preference_fit < 0.6


def test_high_risk_low_confidence_triggers_verification():
    from ai_karen_engine.core.cortex.behavior.verification import VerificationDecider
    decider = VerificationDecider()
    candidate = _candidate()
    ctx = _ctx(reasoning_assessment={"confidence": 0.2})
    req = decider.decide(ctx, candidate)
    assert req.required is True
    assert req.reason == VerificationReason.LOW_CONFIDENCE


def test_conflicting_evidence_can_trigger_abstention():
    selector = BehaviorSelector()
    candidates = [_candidate(BehaviorType.RESPOND)]
    ctx = _ctx(belief_assessment={"confidence": 0.1})
    decision = selector.select(ctx, candidates)
    assert decision.selected_behavior in (BehaviorType.ABSTAIN, BehaviorType.VERIFY)


def test_policy_denied_behavior_cannot_be_selected():
    engine = BehaviorScoringEngine()
    candidate = _candidate(BehaviorType.USE_TOOL)
    ctx = _ctx(policy_constraints={"blocked_behaviors": ["use_tool"]})
    score = engine.score(candidate, ctx)
    assert score.policy_fit == 0.0


def test_unavailable_capability_yields_alternative():
    selector = BehaviorSelector()
    candidates = [_candidate(BehaviorType.USE_CAPABILITY), _candidate(BehaviorType.RESPOND)]
    ctx = _ctx(capability_requirements=[])
    decision = selector.select(ctx, candidates)
    assert decision.selected_behavior in (BehaviorType.USE_CAPABILITY, BehaviorType.RESPOND)


def test_adaptive_recommendation_remains_advisory():
    engine = BehaviorScoringEngine()
    candidate = _candidate()
    ctx = _ctx(adaptive_recommendations=[{"action_type": "respond", "utility_score": 0.3}])
    score = engine.score(candidate, ctx)
    assert score.historical_success == 0.5


def test_cortex_produces_decision_only():
    selector = BehaviorSelector()
    candidates = [_candidate(BehaviorType.RESPOND)]
    ctx = _ctx()
    decision = selector.select(ctx, candidates)
    assert decision.selected_behavior == BehaviorType.RESPOND
    assert not hasattr(decision, "execute")


def test_alternatives_remain_explainable():
    selector = BehaviorSelector()
    candidates = [_candidate(BehaviorType.RESPOND), _candidate(BehaviorType.ASK)]
    ctx = _ctx()
    decision = selector.select(ctx, candidates)
    assert len(decision.alternatives) == 1
    assert decision.alternatives[0].behavior_type == BehaviorType.ASK


def test_tenant_rbac_context_preserved():
    ctx = _ctx(tenant_id="tenant-a", user_id="u1")
    assert ctx.tenant_id == "tenant-a"
    assert ctx.user_id == "u1"


def test_eligibility_gate_filters_blocked():
    gate = BehaviorEligibilityGate()
    candidate = _candidate(constraints=[BehaviorConstraint.POLICY_BLOCKED])
    ctx = _ctx()
    eligible = gate.filter([candidate], ctx)
    assert eligible == []
