from __future__ import annotations

from ai_karen_engine.core.contracts.cognitive import (
    ReasoningDepth,
    VerificationReason,
    VerificationRequirement,
)
from ai_karen_engine.core.cortex.behavior.contracts import (
    BehaviorCandidate,
    BehaviorConstraint,
    BehaviorDecision,
    BehaviorSelectionContext,
    BehaviorType,
)
from ai_karen_engine.core.cortex.behavior.eligibility import BehaviorEligibilityGate
from ai_karen_engine.core.cortex.behavior.scoring import BehaviorScoringEngine


class BehaviorSelector:
    """Canonical CORTEX behavior selector.

    Pipeline: hard eligibility -> canonical scoring -> final decision. CORTEX
    decides; Runtime executes.
    """

    def __init__(
        self,
        eligibility_gate: BehaviorEligibilityGate | None = None,
        scoring_engine: BehaviorScoringEngine | None = None,
    ) -> None:
        self.eligibility_gate = eligibility_gate or BehaviorEligibilityGate()
        self.scoring_engine = scoring_engine or BehaviorScoringEngine()

    def select(
        self,
        context: BehaviorSelectionContext,
        candidates: list[BehaviorCandidate],
    ) -> BehaviorDecision:
        eligible = self.eligibility_gate.filter(candidates, context)
        if not eligible:
            return BehaviorDecision(
                decision_id=f"bd-{context.request_id}",
                selected_behavior=BehaviorType.ABSTAIN,
                confidence=0.0,
                reason_codes=["no_eligible_candidates"],
                policy_decision_ref=context.policy_constraints.decision_id,
            )

        scored = [
            (self.scoring_engine.score(candidate, context), candidate)
            for candidate in eligible
        ]
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
