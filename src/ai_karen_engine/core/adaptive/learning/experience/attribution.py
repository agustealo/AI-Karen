from __future__ import annotations

import logging

from ai_karen_engine.core.adaptive.learning.experience.contracts import (
    ExperienceObservation,
    OutcomeAssessment,
    OutcomeAttribution,
)

logger = logging.getLogger(__name__)


class AttributionEngine:
    """Attributes outcomes to contributing factors."""

    def attribute(self, experience: ExperienceObservation, assessment: OutcomeAssessment) -> OutcomeAttribution:
        """Attribute outcome to contributing factors."""
        primary = "unknown"
        if assessment.task_completion > 0.8:
            primary = "capability"
        elif assessment.user_acceptance > 0.8:
            primary = "user_clarification"
        elif assessment.correction_needed:
            primary = "memory"

        return OutcomeAttribution(
            memory_contribution=0.3 if experience.belief_refs else 0.0,
            reasoning_strategy_contribution=0.3,
            capability_contribution=assessment.task_completion,
            user_clarification_contribution=assessment.user_acceptance,
            verification_contribution=0.1,
            workflow_contribution=0.1,
            fallback_contribution=0.0,
            uncertainty=0.2,
            primary_driver=primary,
        )
