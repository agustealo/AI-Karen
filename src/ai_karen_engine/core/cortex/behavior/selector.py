from __future__ import annotations

import logging

from ai_karen_engine.core.contracts.cognitive import BehaviorConfidence
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
from ai_karen_engine.core.cortex.behavior.eligibility import BehaviorEligibilityGate

logger = logging.getLogger(__name__)


class BehaviorSelector:
    """Selects the best behavior from typed cognitive signals."""

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
                confidence=BehaviorConfidence(0.0),
                reason_codes=["no_eligible_candidates"],
            )

        scored = [(self._score(candidate, context), candidate) for candidate in hard_filtered]
        scored.sort(key=lambda item: item[0].utility, reverse=True)
        best_score, best = scored[0]

        if best_score.utility <= 0.0:
            return BehaviorDecision(
                decision_id=f"bd-{context.request_id}",
                selected_behavior=BehaviorType.ABSTAIN,
                confidence=BehaviorConfidence(0.0),
                reason_codes=["zero_utility"],
            )

        belief_confidence = float(context.belief.confidence) if context.belief else 1.0
        if belief_confidence < 0.3 and best.behavior_type not in (
            BehaviorType.VERIFY,
            BehaviorType.ABSTAIN,
        ):
            return BehaviorDecision(
                decision_id=f"bd-{context.request_id}",
                selected_behavior=BehaviorType.ABSTAIN,
                confidence=BehaviorConfidence(belief_confidence),
                reason_codes=["low_epistemic_confidence_abstain"],
            )

        requires_verification = self._evaluate_verification(best, context)
        return BehaviorDecision(
            decision_id=f"bd-{context.request_id}",
            selected_behavior=best.behavior_type,
            alternatives=[candidate for _, candidate in scored[1:]],
            confidence=BehaviorConfidence(best_score.confidence),
            reason_codes=best.reason_codes,
            evidence_refs=best.evidence_refs,
            goal_refs=best.goal_refs,
            belief_refs=best.belief_refs,
            memory_refs=best.memory_refs,
            requires_verification=requires_verification,
            requires_approval=(
                BehaviorConstraint.REQUIRES_APPROVAL in best.constraints
                or bool(context.policy and context.policy.approval_required)
            ),
            degraded=BehaviorConstraint.DEGRADED in best.constraints,
            policy_decision_ref=context.policy.policy_id if context.policy else None,
        )

    def _score(
        self,
        candidate: BehaviorCandidate,
        context: BehaviorSelectionContext,
    ) -> BehaviorScoreComponents:
        score = BehaviorScoreComponents()
        score.confidence = float(candidate.confidence)
        score.goal_alignment = self._score_goals(candidate, context)
        score.belief_support = self._score_belief(candidate, context)
        score.salience_fit = self._score_salience(candidate, context)
        score.user_preference_fit = 0.5 if context.user_model_ref else 0.4
        score.historical_success = self._score_adaptive(candidate, context)
        score.policy_fit = self._score_policy(candidate, context)
        score.capability_fit = self._score_capability(candidate, context.capability_requirements)
        score.risk = self._score_risk(candidate, context)
        score.interruption_cost = 0.3 if candidate.behavior_type == BehaviorType.ASK else 0.1
        score.verification_value = 0.9 if candidate.behavior_type == BehaviorType.VERIFY else 0.1
        return score

    def _score_goals(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> float:
        if not context.goals:
            return 0.5
        affinities = [goal.affinity.get(candidate.behavior_type.value) for goal in context.goals]
        explicit = [value for value in affinities if value is not None]
        if explicit:
            return max(0.0, min(1.0, max(explicit)))
        if all(goal.blocked for goal in context.goals):
            return 0.2
        return 0.6

    def _score_belief(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> float:
        confidence = float(context.belief.confidence) if context.belief else 0.5
        if candidate.behavior_type == BehaviorType.ABSTAIN:
            return 1.0 - confidence
        return confidence

    def _score_salience(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> float:
        if context.salience is None:
            return 0.5
        dimensions = context.salience.dimensions
        if candidate.behavior_type == BehaviorType.VERIFY:
            return max(
                dimensions.get("risk", 0.0),
                dimensions.get("contradiction", 0.0),
                dimensions.get("surprise", 0.0),
            )
        if candidate.behavior_type == BehaviorType.RECALL:
            return max(
                dimensions.get("goal_relevance", 0.0),
                dimensions.get("unresolved_state", 0.0),
                context.salience.overall * 0.5,
            )
        return context.salience.overall * context.salience.modulation

    def _score_adaptive(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> float:
        if context.adaptive is None:
            return 0.5
        for recommendation in context.adaptive.recommendations:
            if recommendation.action_type == candidate.behavior_type.value:
                return max(0.0, min(1.0, recommendation.utility_score))
        return max(0.0, min(1.0, context.adaptive.utility_score))

    def _score_policy(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> float:
        if context.policy is None:
            return 1.0
        if candidate.behavior_type.value in context.policy.blocked_behaviors:
            return 0.0
        return 1.0

    def _score_capability(self, candidate: BehaviorCandidate, requirements: list[str]) -> float:
        if not requirements:
            return 0.8
        return 0.9 if candidate.behavior_type == BehaviorType.USE_CAPABILITY else 0.7

    def _score_risk(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> float:
        if candidate.behavior_type in (BehaviorType.REFUSE, BehaviorType.ABSTAIN):
            return 0.0
        return context.policy.risk_level if context.policy else 0.0

    def _evaluate_verification(
        self,
        candidate: BehaviorCandidate,
        context: BehaviorSelectionContext,
    ) -> VerificationRequirement | None:
        if candidate.behavior_type == BehaviorType.VERIFY:
            return VerificationRequirement(
                required=True,
                reason=VerificationReason.LOW_CONFIDENCE,
                depth=VerificationDepth.STANDARD,
                source="cortex",
            )
        if context.meta and context.meta.reasoning_confidence < 0.4:
            return VerificationRequirement(
                required=True,
                reason=VerificationReason.LOW_REASONING_CONFIDENCE,
                depth=VerificationDepth.STANDARD,
                source="cortex",
            )
        if context.belief and context.belief.contradictions:
            return VerificationRequirement(
                required=True,
                reason=VerificationReason.CONFLICTING_EVIDENCE,
                depth=VerificationDepth.STANDARD,
                source="cortex",
            )
        return None
