from __future__ import annotations

import logging

from ai_karen_engine.core.reasoning.meta.contracts import (
    MetaCognitiveState,
    MetaReasonCode,
    VerificationNeedAssessment,
)

logger = logging.getLogger(__name__)


class MetaVerificationEngine:
    """Determines when verification is needed based on meta-cognitive state."""

    def assess(self, state: MetaCognitiveState, confidence: float, risk: float, freshness: float) -> VerificationNeedAssessment:
        """Assess verification need."""
        if state.evidence_consistency < 0.3:
            return VerificationNeedAssessment(required=True, reason=MetaReasonCode.CONFLICTING_EVIDENCE, urgency=0.9)
        if confidence < 0.3:
            return VerificationNeedAssessment(required=True, reason=MetaReasonCode.LOW_MEMORY_CONFIDENCE, urgency=0.8)
        if risk > 0.7:
            return VerificationNeedAssessment(required=True, reason=MetaReasonCode.HIGH_RISK_UNCERTAIN_CLAIM, urgency=0.7)
        if freshness < 0.2:
            return VerificationNeedAssessment(required=True, reason=MetaReasonCode.STALE_MEMORY, urgency=0.5)
        return VerificationNeedAssessment(required=False)
