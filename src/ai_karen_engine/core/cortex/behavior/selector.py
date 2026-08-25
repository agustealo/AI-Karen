from __future__ import annotations

import logging
from typing import Any

from ai_karen_engine.core.cortex.behavior.contracts import (
    BehaviorCandidate,
    BehaviorConstraint,
    BehaviorDecision,
    BehaviorScoreComponents,
    BehaviorSelectionContext,
    BehaviorType,
    VerificationDepth,
    VerificationReason,
    VerificationRequirement,
)

logger = logging.getLogger(__name__)


class BehaviorSelector:
    """Selects the best behavior from candidates using cognitive signals."""

    def select(self, context: BehaviorSelectionContext, candidates: list[BehaviorCandidate]) -> BehaviorDecision:
        """Select the best behavior from candidates."""
        if not candidates:
            return BehaviorDecision(
                decision_id=f"bd-{context.request_id}",
                selected_behavior=BehaviorType.ABSTAIN,
                confidence=0.0,
                reason_codes=["no_candidates"],
            )

        scored = [(self._score(c, context), c) for c in candidates]
        scored.sort(key=lambda x: x[0].utility, reverse=True)

        best_score, best = scored[0]
        if best_score.utility <= 0.0:
            return BehaviorDecision(
                decision_id=f"bd-{context.request_id}",
                selected_behavior=BehaviorType.ABSTAIN,
                confidence=0.0,
                reason_codes=["zero_utility"],
            )

        if context.belief_assessment.get("confidence", 1.0) < 0.3 and best.behavior_type not in (BehaviorType.VERIFY, BehaviorType.ABSTAIN):
            return BehaviorDecision(
                decision_id=f"bd-{context.request_id}",
                selected_behavior=BehaviorType.ABSTAIN,
                confidence=context.belief_assessment.get("confidence", 0.0),
                reason_codes=["low_confidence_abstain"],
            )

        requires_verification = self._evaluate_verification(best, context)

        return BehaviorDecision(
            decision_id=f"bd-{context.request_id}",
            selected_behavior=best.behavior_type,
            alternatives=[c for _, c in scored[1:]],
            confidence=best_score.confidence,
            reason_codes=best.reason_codes,
            evidence_refs=best.evidence_refs,
            goal_refs=best.goal_refs,
            belief_refs=best.belief_refs,
            memory_refs=best.memory_refs,
            requires_verification=requires_verification,
            requires_approval=BehaviorConstraint.REQUIRES_APPROVAL in best.constraints,
            degraded=BehaviorConstraint.DEGRADED in best.constraints,
            policy_decision_ref=context.policy_constraints.get("decision_id"),
        )

    def _score(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> BehaviorScoreComponents:
        s = BehaviorScoreComponents()
        s.confidence = candidate.confidence

        if context.goal_state:
            s.goal_alignment = self._score_goal(candidate, context.goal_state)
        if context.belief_assessment:
            s.belief_support = self._score_belief(candidate, context.belief_assessment)
        if context.salience:
            s.salience_fit = self._score_salience(candidate, context.salience)
        if context.user_model:
            s.user_preference_fit = self._score_user(candidate, context.user_model)
        if context.adaptive_recommendations:
            s.historical_success = self._score_adaptive(candidate, context.adaptive_recommendations)
        if context.policy_constraints:
            s.policy_fit = self._score_policy(candidate, context.policy_constraints)

        s.capability_fit = self._score_capability(candidate, context.capability_requirements)
        s.risk = self._score_risk(candidate, context)
        s.interruption_cost = self._score_interruption(candidate, context)
        s.verification_value = self._score_verification(candidate, context)
        return s

    def _score_goal(self, candidate: BehaviorCandidate, goal_state: dict[str, Any]) -> float:
        if not goal_state:
            return 0.5
        active = goal_state.get("active_goals", [])
        if not active:
            return 0.5
        return 0.9 if candidate.behavior_type in (BehaviorType.USE_WORKFLOW, BehaviorType.REASON, BehaviorType.RECALL) else 0.4

    def _score_belief(self, candidate: BehaviorCandidate, belief_assessment: dict[str, Any]) -> float:
        confidence = belief_assessment.get("confidence", 0.5)
        if candidate.behavior_type == BehaviorType.ABSTAIN:
            return 1.0 - confidence
        return confidence

    def _score_salience(self, candidate: BehaviorCandidate, salience: dict[str, Any]) -> float:
        overall = salience.get("overall", 0.0)
        if candidate.behavior_type == BehaviorType.ASK:
            return overall if overall > 0.5 else 0.3
        return overall * 0.8

    def _score_user(self, candidate: BehaviorCandidate, user_model: dict[str, Any]) -> float:
        prefers_action = user_model.get("prefers_action_over_clarification", True)
        if candidate.behavior_type == BehaviorType.ASK and not prefers_action:
            return 0.2
        return 0.7 if prefers_action else 0.5

    def _score_adaptive(self, candidate: BehaviorCandidate, recommendations: list[dict[str, Any]]) -> float:
        for rec in recommendations:
            if rec.get("action_type") == candidate.behavior_type.value:
                return rec.get("utility_score", 0.5)
        return 0.5

    def _score_policy(self, candidate: BehaviorCandidate, policy_constraints: dict[str, Any]) -> float:
        blocked = policy_constraints.get("blocked_behaviors", [])
        if candidate.behavior_type.value in blocked:
            return 0.0
        return 1.0

    def _score_capability(self, candidate: BehaviorCandidate, requirements: list[str]) -> float:
        if not requirements:
            return 0.8
        if candidate.behavior_type == BehaviorType.USE_CAPABILITY:
            return 0.9 if requirements else 0.2
        return 0.7

    def _score_risk(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> float:
        risk = context.policy_constraints.get("risk", 0.0)
        if candidate.behavior_type in (BehaviorType.REFUSE, BehaviorType.ABSTAIN):
            return 0.0
        return risk

    def _score_interruption(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> float:
        if candidate.behavior_type == BehaviorType.ASK:
            return 0.3
        return 0.1

    def _score_verification(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> float:
        if candidate.behavior_type == BehaviorType.VERIFY:
            return 0.9
        return 0.1

    def _evaluate_verification(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> VerificationRequirement | None:
        if candidate.behavior_type == BehaviorType.VERIFY:
            return VerificationRequirement(required=True, reason=VerificationReason.LOW_CONFIDENCE, depth=VerificationDepth.STANDARD)
        if context.reasoning_assessment.get("confidence", 1.0) < 0.4:
            return VerificationRequirement(required=True, reason=VerificationReason.LOW_CONFIDENCE, depth=VerificationDepth.STANDARD)
        return None
