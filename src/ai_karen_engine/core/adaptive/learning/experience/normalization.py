from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ai_karen_engine.core.adaptive.contracts import ActionOutcomeObservation
from ai_karen_engine.core.adaptive.learning.experience.contracts import (
    ExperienceObservation,
    OutcomeAssessment,
    OutcomeAssessmentStatus,
)

logger = logging.getLogger(__name__)


class ExperienceNormalizer:
    """Normalizes raw execution outcomes into semantic experience observations."""

    def normalize(self, outcome: ActionOutcomeObservation) -> ExperienceObservation:
        """Convert an ActionOutcomeObservation into an ExperienceObservation."""
        assessment = self._assess_outcome(outcome)
        return ExperienceObservation(
            observation_id=f"exp-{outcome.observation_id}",
            what_was_tried=outcome.action_type or "unknown",
            why_chosen="adaptive_recommendation",
            task_signature_ref=outcome.task_signature_ref,
            goal_refs=[],
            belief_refs=[],
            behavior_decision_ref=outcome.observation_id,
            expected_outcome={"status": "success"},
            actual_outcome={
                "status": outcome.execution_status,
                "tool_success": outcome.tool_success,
                "completion": outcome.completion,
            },
            user_feedback=outcome.user_feedback,
            tenant_id=outcome.user_scope.get("tenant_id", "default"),
            user_id=outcome.user_scope.get("user_id"),
        )

    def _assess_outcome(self, outcome: ActionOutcomeObservation) -> OutcomeAssessment:
        status = OutcomeAssessmentStatus.UNKNOWN
        if outcome.execution_status == "success" and outcome.completion:
            status = OutcomeAssessmentStatus.SUCCESS
        elif outcome.execution_status == "failure":
            status = OutcomeAssessmentStatus.FAILURE
        elif outcome.correction:
            status = OutcomeAssessmentStatus.PARTIAL_SUCCESS

        return OutcomeAssessment(
            status=status,
            task_completion=1.0 if outcome.completion else 0.0,
            correctness=1.0 if outcome.tool_success else 0.0,
            user_acceptance=1.0 if outcome.user_feedback in ("accepted", "thumbs_up") else 0.0,
            correction_needed=outcome.correction,
        )
