from __future__ import annotations

from ai_karen_engine.core.cortex.behavior.contracts import (
    BehaviorCandidate,
    BehaviorScoreComponents,
    BehaviorSelectionContext,
    BehaviorType,
)


class BehaviorScoringEngine:
    """Scores behavior candidates using explainable components."""

    def score(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> BehaviorScoreComponents:
        return BehaviorScoreComponents(
            goal_alignment=self._goal_alignment(candidate, context),
            belief_support=self._belief_support(candidate, context),
            salience_fit=self._salience_fit(candidate, context),
            user_preference_fit=self._user_preference(candidate, context),
            historical_success=self._historical(candidate, context),
            risk=self._risk(candidate, context),
            policy_fit=self._policy_fit(candidate, context),
            confidence=candidate.confidence,
            interruption_cost=self._interruption(candidate, context),
            verification_value=self._verification(candidate, context),
            capability_fit=self._capability(candidate, context),
        )

    def _goal_alignment(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        gs = ctx.goal_state or {}
        active = gs.get("active_goals", [])
        if not active:
            return 0.5
        return 0.9 if c.behavior_type in (BehaviorType.USE_WORKFLOW, BehaviorType.REASON, BehaviorType.RECALL) else 0.4

    def _belief_support(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        ba = ctx.belief_assessment or {}
        return float(ba.get("confidence", 0.5))

    def _salience_fit(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        s = ctx.salience or {}
        overall = float(s.get("overall", 0.0))
        return overall * 0.8

    def _user_preference(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        um = ctx.user_model or {}
        return 0.7 if um.get("prefers_action_over_clarification", True) else 0.5

    def _historical(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        for rec in ctx.adaptive_recommendations:
            if rec.get("action_type") == c.behavior_type.value:
                return max(0.5, float(rec.get("utility_score", 0.5)))
        return 0.5

    def _risk(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        return float(ctx.policy_constraints.get("risk", 0.0))

    def _policy_fit(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        blocked = ctx.policy_constraints.get("blocked_behaviors", [])
        return 0.0 if c.behavior_type.value in blocked else 1.0

    def _interruption(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        return 0.3 if c.behavior_type == BehaviorType.ASK else 0.1

    def _verification(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        return 0.9 if c.behavior_type == BehaviorType.VERIFY else 0.1

    def _capability(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        reqs = ctx.capability_requirements or []
        if not reqs:
            return 0.8
        return 0.9 if c.behavior_type == BehaviorType.USE_CAPABILITY else 0.2
