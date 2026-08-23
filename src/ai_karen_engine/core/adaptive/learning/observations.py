"""Action outcome observations.

Converts execution outcomes into action observations for learning.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from ai_karen_engine.core.adaptive.contracts import ActionOutcomeObservation
from ai_karen_engine.core.runtime.outcome.contracts import OutcomeRecord

logger = logging.getLogger(__name__)


class AdaptiveObservationProcessor:
    """Processes execution outcomes into adaptive observations."""

    def process_outcome(self, outcome: OutcomeRecord) -> ActionOutcomeObservation | None:
        """Convert an OutcomeRecord into an ActionOutcomeObservation."""
        if outcome is None:
            return None

        execution = outcome.execution_outcome
        user_outcome = outcome.user_outcome

        action_type = self._infer_action_type(outcome)
        target_id = self._infer_target_id(outcome)

        observation = ActionOutcomeObservation(
            observation_id=f"obs-{uuid.uuid4().hex}",
            source_outcome_id=outcome.outcome_id,
            task_signature_ref=self._signature_ref_from_outcome(outcome),
            user_scope={
                "user_id": outcome.user_id,
                "tenant_id": outcome.tenant_id,
                "conversation_id": outcome.conversation_id,
            },
            action_type=action_type,
            target_id=target_id,
            execution_status=execution.status.value if execution else "unknown",
            latency_ms=float(execution.latency_ms) if execution and execution.latency_ms else 0.0,
            fallback_used=bool(execution.fallback_count > 0) if execution else False,
            tool_success=execution.tool_success if execution else None,
            user_feedback=user_outcome.feedback_type.value if user_outcome and user_outcome.feedback_type else None,
            correction=user_outcome.feedback_type.value == "user_correction" if user_outcome and user_outcome.feedback_type else False,
            completion=self._is_completion(outcome),
        )
        return observation

    def _infer_action_type(self, outcome: OutcomeRecord) -> str:
        metadata = outcome.metadata or {}
        return metadata.get("action_type", "respond_directly")

    def _infer_target_id(self, outcome: OutcomeRecord) -> str | None:
        metadata = outcome.metadata or {}
        return metadata.get("target_id")

    def _signature_ref_from_outcome(self, outcome: OutcomeRecord) -> dict[str, Any]:
        metadata = outcome.metadata or {}
        return metadata.get("task_signature_ref", {})

    def _is_completion(self, outcome: OutcomeRecord) -> bool:
        execution = outcome.execution_outcome
        if execution and execution.response_completed:
            return True
        user_outcome = outcome.user_outcome
        if user_outcome and user_outcome.feedback_type:
            return user_outcome.feedback_type.value == "task_completion_confirmation"
        return False
