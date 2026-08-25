from __future__ import annotations

import logging

from ai_karen_engine.core.contracts.cognitive import ReasoningDepth, VerificationRequirement
from ai_karen_engine.core.reasoning.meta.contracts import MetaCognitiveState, MetaReasonCode

logger = logging.getLogger(__name__)


class MetaVerificationEngine:
    """Advises CORTEX when verification should be considered.

    This engine never authorizes or executes verification.
    """

    def assess(
        self,
        state: MetaCognitiveState,
        confidence: float,
        risk: float,
        freshness: float,
    ) -> VerificationRequirement:
        if state.evidence_consistency < 0.3:
            return VerificationRequirement(
                required=True,
                reason=MetaReasonCode.EVIDENCE_INCONSISTENT,
                depth=ReasoningDepth.STANDARD,
                urgency=0.9,
                source="meta",
            )
        if confidence < 0.3:
            return VerificationRequirement(
                required=True,
                reason=MetaReasonCode.LOW_REASONING_CONFIDENCE,
                depth=ReasoningDepth.STANDARD,
                urgency=0.8,
                source="meta",
            )
        if risk > 0.7:
            return VerificationRequirement(
                required=True,
                reason=MetaReasonCode.HIGH_RISK_UNCERTAIN_CLAIM,
                depth=ReasoningDepth.DEEP,
                urgency=0.7,
                source="meta",
            )
        if freshness < 0.2:
            return VerificationRequirement(
                required=True,
                reason=MetaReasonCode.STALE_EVIDENCE,
                depth=ReasoningDepth.STANDARD,
                urgency=0.5,
                source="meta",
            )
        return VerificationRequirement(required=False, source="meta")
