from __future__ import annotations

from ai_karen_engine.core.contracts.cognitive import ReasoningDepth
from ai_karen_engine.core.cortex.behavior.contracts import (
    BehaviorCandidate,
    BehaviorSelectionContext,
    BehaviorType,
    VerificationReason,
    VerificationRequirement,
)


class VerificationDecider:
    """CORTEX decision layer for the canonical verification contract."""

    def decide(
        self,
        context: BehaviorSelectionContext,
        candidate: BehaviorCandidate,
    ) -> VerificationRequirement:
        if candidate.behavior_type == BehaviorType.VERIFY:
            return VerificationRequirement(
                required=True,
                reason=VerificationReason.LOW_CONFIDENCE,
                depth=ReasoningDepth.STANDARD,
                source="cortex",
            )

        if context.meta and context.meta.reasoning_confidence < 0.4:
            return VerificationRequirement(
                required=True,
                reason=VerificationReason.LOW_REASONING_CONFIDENCE,
                depth=ReasoningDepth.STANDARD,
                urgency=0.8,
                source="cortex",
            )

        if context.policy and context.policy.risk_level > 0.7:
            return VerificationRequirement(
                required=True,
                reason=VerificationReason.HIGH_RISK,
                depth=ReasoningDepth.DEEP,
                urgency=context.policy.risk_level,
                source="cortex",
            )

        if context.belief and context.belief.contradictions:
            return VerificationRequirement(
                required=True,
                reason=VerificationReason.CONFLICTING_EVIDENCE,
                depth=ReasoningDepth.STANDARD,
                urgency=0.8,
                source="cortex",
            )

        return VerificationRequirement(required=False, source="cortex")
