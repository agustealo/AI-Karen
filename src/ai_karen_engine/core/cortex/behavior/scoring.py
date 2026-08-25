from __future__ import annotations

from ai_karen_engine.core.cortex.behavior.contracts import (
    BehaviorCandidate,
    BehaviorConstraint,
    BehaviorScoreComponents,
    BehaviorSelectionContext,
    BehaviorType,
)


class BehaviorScoringEngine:
    """Single explainable scoring implementation used by CORTEX selection."""

    def score(
        self,
        candidate: BehaviorCandidate,
        context: BehaviorSelectionContext,
    ) -> BehaviorScoreComponents:
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

    def _goal_alignment(
        self,
        candidate: BehaviorCandidate,
        context: BehaviorSelectionContext,
    ) -> float:
        goals = context.goal_state
        if not goals.active_goal_ids:
            return 0.5
        if candidate.behavior_type in (
            BehaviorType.USE_WORKFLOW,
            BehaviorType.REASON,
            BehaviorType.RECALL,
        ):
            return 0.9
        if candidate.behavior_type in (BehaviorType.WAIT, BehaviorType.DEFER) and goals.blocked_goal_ids:
            return 0.8
        return 0.4

    def _belief_support(
        self,
        candidate: BehaviorCandidate,
        context: BehaviorSelectionContext,
    ) -> float:
        confidence = context.belief_assessment.epistemic_confidence
        if candidate.behavior_type == BehaviorType.ABSTAIN:
            return 1.0 - confidence
        if candidate.behavior_type == BehaviorType.VERIFY and (
            context.belief_assessment.contradiction_count > 0
            or context.belief_assessment.stale
        ):
            return max(0.8, 1.0 - confidence)
        return confidence

    def _salience_fit(
        self,
        candidate: BehaviorCandidate,
        context: BehaviorSelectionContext,
    ) -> float:
        salience = context.salience
        effective = max(0.0, salience.activation - salience.inhibition)
        if candidate.behavior_type == BehaviorType.VERIFY and "risk" in salience.dominant_dimensions:
            return max(effective, 0.8)
        return max(effective, salience.overall * 0.8)

    def _user_preference(
        self,
        candidate: BehaviorCandidate,
        context: BehaviorSelectionContext,
    ) -> float:
        prefers_action = context.user_model.prefers_action_over_clarification
        if candidate.behavior_type == BehaviorType.ASK:
            return 0.2 if prefers_action else 0.8
        return 0.7 if prefers_action else 0.5

    def _historical(
        self,
        candidate: BehaviorCandidate,
        context: BehaviorSelectionContext,
    ) -> float:
        for recommendation in context.adaptive_recommendations:
            if recommendation.action_type == candidate.behavior_type.value:
                return recommendation.utility_score
        return 0.5

    def _risk(
        self,
        candidate: BehaviorCandidate,
        context: BehaviorSelectionContext,
    ) -> float:
        if candidate.behavior_type in (BehaviorType.REFUSE, BehaviorType.ABSTAIN):
            return 0.0
        return context.policy_constraints.risk

    def _policy_fit(
        self,
        candidate: BehaviorCandidate,
        context: BehaviorSelectionContext,
    ) -> float:
        if candidate.behavior_type.value in context.policy_constraints.blocked_behaviors:
            return 0.0
        if BehaviorConstraint.POLICY_BLOCKED in candidate.constraints:
            return 0.0
        return 1.0

    def _interruption(
        self,
        candidate: BehaviorCandidate,
        context: BehaviorSelectionContext,
    ) -> float:
        return 0.3 if candidate.behavior_type == BehaviorType.ASK else 0.1

    def _verification(
        self,
        candidate: BehaviorCandidate,
        context: BehaviorSelectionContext,
    ) -> float:
        return 0.9 if candidate.behavior_type == BehaviorType.VERIFY else 0.1

    def _capability(
        self,
        candidate: BehaviorCandidate,
        context: BehaviorSelectionContext,
    ) -> float:
        if not context.capability_requirements:
            return 0.8
        return 0.9 if candidate.behavior_type == BehaviorType.USE_CAPABILITY else 0.2
