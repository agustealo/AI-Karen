from __future__ import annotations

from ai_karen_engine.core.cortex.behavior.contracts import (
    BehaviorCandidate,
    BehaviorConstraint,
    BehaviorScoreComponents,
    BehaviorSelectionContext,
    BehaviorType,
)


class BehaviorScoringEngine:
    """Scores behavior candidates using the typed cognitive boundary."""

    def score(
        self,
        candidate: BehaviorCandidate,
        context: BehaviorSelectionContext,
    ) -> BehaviorScoreComponents:
        return BehaviorScoreComponents(
            goal_alignment=self._goal_alignment(candidate, context),
            belief_support=self._belief_support(candidate, context),
            salience_fit=self._salience_fit(candidate, context),
            user_preference_fit=0.5 if context.user_model_ref else 0.4,
            historical_success=self._historical(candidate, context),
            risk=self._risk(candidate, context),
            policy_fit=self._policy_fit(candidate, context),
            confidence=float(candidate.confidence),
            interruption_cost=self._interruption(candidate, context),
            verification_value=self._verification(candidate, context),
            capability_fit=self._capability(candidate, context),
        )

    def _goal_alignment(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        if not ctx.goals:
            return 0.5
        explicit = [goal.affinity.get(c.behavior_type.value) for goal in ctx.goals]
        scores = [value for value in explicit if value is not None]
        if scores:
            return max(0.0, min(1.0, max(scores)))
        if all(goal.blocked for goal in ctx.goals):
            return 0.2
        return 0.6

    def _belief_support(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        if ctx.belief is None:
            return 0.5
        confidence = float(ctx.belief.confidence)
        return 1.0 - confidence if c.behavior_type == BehaviorType.ABSTAIN else confidence

    def _salience_fit(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        if ctx.salience is None:
            return 0.5
        if c.behavior_type == BehaviorType.VERIFY:
            dimensions = ctx.salience.dimensions
            return max(
                dimensions.get("risk", 0.0),
                dimensions.get("contradiction", 0.0),
                dimensions.get("surprise", 0.0),
            )
        return ctx.salience.overall * ctx.salience.modulation

    def _historical(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        if ctx.adaptive is None:
            return 0.5
        for rec in ctx.adaptive.recommendations:
            if rec.action_type == c.behavior_type.value:
                return max(0.0, min(1.0, rec.utility_score))
        return max(0.0, min(1.0, ctx.adaptive.utility_score))

    def _risk(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        if c.behavior_type in (BehaviorType.REFUSE, BehaviorType.ABSTAIN):
            return 0.0
        return ctx.policy.risk_level if ctx.policy else 0.0

    def _policy_fit(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        if BehaviorConstraint.POLICY_BLOCKED in c.constraints:
            return 0.0
        if ctx.policy and c.behavior_type.value in ctx.policy.blocked_behaviors:
            return 0.0
        return 1.0

    def _interruption(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        return 0.3 if c.behavior_type == BehaviorType.ASK else 0.1

    def _verification(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        return 0.9 if c.behavior_type == BehaviorType.VERIFY else 0.1

    def _capability(self, c: BehaviorCandidate, ctx: BehaviorSelectionContext) -> float:
        if not ctx.capability_requirements:
            return 0.8
        return 0.9 if c.behavior_type == BehaviorType.USE_CAPABILITY else 0.7
