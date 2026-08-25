from __future__ import annotations

from ai_karen_engine.core.contracts.cognitive import VerificationReason, VerificationRequirement
from ai_karen_engine.core.cortex.behavior.contracts import (
    BehaviorCandidate,
    BehaviorConstraint,
    BehaviorDecision,
    BehaviorScoreComponents,
    BehaviorSelectionContext,
    BehaviorType,
    ReasoningDepth,
)
from ai_karen_engine.core.cortex.behavior.eligibility import BehaviorEligibilityGate


class BehaviorSelector:
    """Canonical CORTEX behavior selector.

    Hard eligibility is always applied before scoring. Policy denial, tenant
    restrictions, and unavailable capabilities are gates rather than utility
    suggestions.
    """

    def __init__(self) -> None:
        self.eligibility_gate = BehaviorEligibilityGate()

    def select(
        self,
        context: BehaviorSelectionContext,
        candidates: list[BehaviorCandidate],
    ) -> BehaviorDecision:
        hard_filtered = self.eligibility_gate.filter(candidates, context)
        if not hard_filtered:
            return BehaviorDecision(
                decision_id=f"bd-{context.request_id}",
                selected_behavior=BehaviorType.ABSTAIN,
                confidence=0.0,
                reason_codes=["no_eligible_candidates"],
                policy_decision_ref=context.policy_constraints.decision_id,
            )

        scored = [(self._score(candidate, context), candidate) for candidate in hard_filtered]
        scored.sort(key=lambda pair: pair[0].utility, reverse=True)
        best_score, best = scored[0]

        if best_score.utility <= 0.0:
            return BehaviorDecision(
                decision_id=f"bd-{context.request_id}",
                selected_behavior=BehaviorType.ABSTAIN,
                confidence=0.0,
                reason_codes=["zero_utility"],
                policy_decision_ref=context.policy_constraints.decision_id,
            )

        if (
            context.belief_assessment.epistemic_confidence < 0.3
            and best.behavior_type not in (BehaviorType.VERIFY, BehaviorType.ABSTAIN)
        ):
            return BehaviorDecision(
                decision_id=f"bd-{context.request_id}",
                selected_behavior=BehaviorType.ABSTAIN,
                confidence=context.belief_assessment.epistemic_confidence,
                reason_codes=["low_epistemic_confidence_abstain"],
                belief_refs=list(context.belief_assessment.active_claim_ids),
                policy_decision_ref=context.policy_constraints.decision_id,
            )

        verification = self._evaluate_verification(best, context)
        return BehaviorDecision(
            decision_id=f"bd-{context.request_id}",
            selected_behavior=best.behavior_type,
            alternatives=[candidate for _, candidate in scored[1:]],
            confidence=best_score.confidence,
            reason_codes=best.reason_codes,
            evidence_refs=best.evidence_refs,
            goal_refs=best.goal_refs,
            belief_refs=best.belief_refs,
            memory_refs=best.memory_refs,
            requires_verification=verification,
            requires_approval=(
                BehaviorConstraint.REQUIRES_APPROVAL in best.constraints
                or context.policy_constraints.requires_approval
            ),
            degraded=(
                BehaviorConstraint.DEGRADED in best.constraints
                or context.memory_signals.degraded
            ),
            policy_decision_ref=context.policy_constraints.decision_id,
        )

    def _score(
        self,
        candidate: BehaviorCandidate,
        context: BehaviorSelectionContext,
    ) -> BehaviorScoreComponents:
        score = BehaviorScoreComponents(confidence=candidate.confidence)
        score.goal_alignment = self._score_goal(candidate, context)
        score.belief_support = self._score_belief(candidate, context)
        score.salience_fit = self._score_salience(candidate, context)
        score.user_preference_fit = self._score_user(candidate, context)
        score.historical_success = self._score_adaptive(candidate, context)
        score.policy_fit = self._score_policy(candidate, context)
        score.capability_fit = self._score_capability(candidate, context)
        score.risk = self._score_risk(candidate, context)
        score.interruption_cost = 0.3 if candidate.behavior_type == BehaviorType.ASK else 0.1
        score.verification_value = 0.9 if candidate.behavior_type == BehaviorType.VERIFY else 0.1
        return score

    def _score_goal(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> float:
        goals = context.goal_state
        if not goals.active_goal_ids:
            return 0.5
        if candidate.behavior_type in (BehaviorType.USE_WORKFLOW, BehaviorType.REASON, BehaviorType.RECALL):
            return 0.9
        if candidate.behavior_type in (BehaviorType.WAIT, BehaviorType.DEFER) and goals.blocked_goal_ids:
            return 0.8
        return 0.4

    def _score_belief(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> float:
        confidence = context.belief_assessment.epistemic_confidence
        if candidate.behavior_type == BehaviorType.ABSTAIN:
            return 1.0 - confidence
        if candidate.behavior_type == BehaviorType.VERIFY and (
            context.belief_assessment.contradiction_count > 0
            or context.belief_assessment.stale
        ):
            return max(0.8, 1.0 - confidence)
        return confidence

    def _score_salience(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> float:
        salience = context.salience
        effective = max(0.0, salience.activation - salience.inhibition)
        if candidate.behavior_type == BehaviorType.VERIFY and "risk" in salience.dominant_dimensions:
            return max(effective, 0.8)
        if candidate.behavior_type == BehaviorType.ASK and "uncertainty" in salience.dominant_dimensions:
            return max(effective, 0.7)
        return max(effective, salience.overall * 0.8)

    def _score_user(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> float:
        prefers_action = context.user_model.prefers_action_over_clarification
        if candidate.behavior_type == BehaviorType.ASK:
            return 0.2 if prefers_action else 0.8
        return 0.7 if prefers_action else 0.5

    def _score_adaptive(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> float:
        for recommendation in context.adaptive_recommendations:
            if recommendation.action_type == candidate.behavior_type.value:
                return recommendation.utility_score
        return 0.5

    def _score_policy(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> float:
        return 0.0 if candidate.behavior_type.value in context.policy_constraints.blocked_behaviors else 1.0

    def _score_capability(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> float:
        if not context.capability_requirements:
            return 0.8
        if candidate.behavior_type == BehaviorType.USE_CAPABILITY:
            return 0.9
        return 0.7

    def _score_risk(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> float:
        if candidate.behavior_type in (BehaviorType.REFUSE, BehaviorType.ABSTAIN):
            return 0.0
        return context.policy_constraints.risk

    def _evaluate_verification(
        self,
        candidate: BehaviorCandidate,
        context: BehaviorSelectionContext,
    ) -> VerificationRequirement | None:
        if candidate.behavior_type == BehaviorType.VERIFY:
            return VerificationRequirement(
                required=True,
                reason=VerificationReason.LOW_CONFIDENCE,
                depth=ReasoningDepth.STANDARD,
                source_stage="cortex",
            )
        if context.belief_assessment.contradiction_count > 0:
            return VerificationRequirement(
                required=True,
                reason=VerificationReason.CONFLICTING_EVIDENCE,
                depth=ReasoningDepth.STANDARD,
                source_stage="cortex",
                evidence_refs=context.belief_assessment.evidence_refs,
            )
        if context.belief_assessment.stale:
            return VerificationRequirement(
                required=True,
                reason=VerificationReason.STALE_MEMORY,
                depth=ReasoningDepth.STANDARD,
                source_stage="cortex",
            )
        if context.reasoning_assessment.reasoning_confidence < 0.4:
            return VerificationRequirement(
                required=True,
                reason=VerificationReason.LOW_REASONING_CONFIDENCE,
                depth=ReasoningDepth.STANDARD,
                source_stage="cortex",
            )
        return None
