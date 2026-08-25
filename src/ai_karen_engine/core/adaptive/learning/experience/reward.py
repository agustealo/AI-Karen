from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ai_karen_engine.core.adaptive.learning.experience.contracts import (
    ExperienceObservation,
    LearningRewardVector,
    OutcomeAssessment,
)

logger = logging.getLogger(__name__)


class RewardComputer:
    """Computes multi-dimensional reward vectors from experiences and assessments."""

    def compute(self, experience: ExperienceObservation, assessment: OutcomeAssessment) -> LearningRewardVector:
        """Compute reward vector from experience and assessment."""
        return LearningRewardVector(
            task_success=assessment.task_completion,
            user_satisfaction=assessment.user_acceptance,
            correctness=assessment.correctness,
            efficiency=max(0.0, 1.0 - (experience.metadata.get("latency_ms", 0.0) / 30000.0)),
            safety=assessment.safety,
            cost=experience.metadata.get("cost", 0.0),
            latency=experience.metadata.get("latency_ms", 0.0) / 30000.0,
            clarification_cost=0.0,
            verification_value=0.0,
        )
