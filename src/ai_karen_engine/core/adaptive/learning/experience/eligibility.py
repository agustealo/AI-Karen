from __future__ import annotations

import logging

from ai_karen_engine.core.adaptive.learning.experience.contracts import (
    ExperienceObservation,
    LearningEligibility,
    LearningEligibilityDecision,
    LearningScope,
    LearningSignal,
    LearningSignalType,
    OutcomeAssessment,
    OutcomeAssessmentStatus,
)

logger = logging.getLogger(__name__)


class EligibilityGate:
    """Determines which experiences should alter behavior."""

    def evaluate(self, experience: ExperienceObservation, assessment: OutcomeAssessment, signal: LearningSignal) -> LearningEligibilityDecision:
        """Evaluate learning eligibility."""
        if signal.scope == LearningScope.GLOBAL and signal.sample_count < 3:
            return LearningEligibilityDecision(action=LearningEligibility.RECORD_ONLY, reason="insufficient_global_samples")
        if assessment.status == OutcomeAssessmentStatus.FAILURE and signal.signal_type == LearningSignalType.RUNTIME_FAILURE:
            return LearningEligibilityDecision(action=LearningEligibility.RECORD_ONLY, reason="infrastructure_failure")
        if assessment.correction_needed:
            return LearningEligibilityDecision(action=LearningEligibility.REFLECT, reason="user_correction")
        if assessment.user_acceptance > 0.8:
            return LearningEligibilityDecision(action=LearningEligibility.UPDATE_PROFILE, reason="high_acceptance")
        return LearningEligibilityDecision(action=LearningEligibility.IGNORE, reason="low_signal")
