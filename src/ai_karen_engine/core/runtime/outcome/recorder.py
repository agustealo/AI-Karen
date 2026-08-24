from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ai_karen_engine.core.observability.context import get_observability_context
from ai_karen_engine.core.runtime.outcome.contracts import (
    ExecutionOutcome,
    ExecutionStatus,
    UserFeedbackType,
    UserOutcome,
)


class OutcomeRecorder:
    """Records execution and user outcomes linked to trajectories.

    This component is observational only. It does not calculate rewards
    or change runtime behavior.
    """

    def __init__(self, store: Any | None = None) -> None:
        self._store = store

    def record_execution_outcome(
        self,
        trajectory_id: str | None = None,
        *,
        decision_observation_id: str | None = None,
        status: ExecutionStatus = ExecutionStatus.FAILURE,
        latency_ms: float | None = None,
        provider_errors: list[str] | None = None,
        fallback_count: int = 0,
        tool_success: bool | None = None,
        plugin_success: bool | None = None,
        schema_valid: bool | None = None,
        response_completed: bool | None = None,
        persistence_success: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record an execution outcome.

        Returns the recorded dict so callers can attach it to observability
        events or API responses.
        """
        ctx = get_observability_context()
        execution = ExecutionOutcome(
            status=status,
            latency_ms=latency_ms,
            provider_errors=provider_errors or [],
            fallback_count=fallback_count,
            tool_success=tool_success,
            plugin_success=plugin_success,
            schema_valid=schema_valid,
            response_completed=response_completed,
            persistence_success=persistence_success,
        )
        payload = execution.to_dict()
        payload.update(
            {
                "outcome_id": f"out_{uuid.uuid4().hex}",
                "trajectory_id": trajectory_id,
                "decision_observation_id": decision_observation_id,
                "request_id": ctx.request_id,
                "correlation_id": ctx.correlation_id,
                "tenant_id": ctx.tenant_id,
                "user_id": ctx.user_id,
                "session_id": ctx.session_id,
                "conversation_id": ctx.conversation_id,
                "recorded_at": datetime.utcnow().isoformat(),
                "source": "runtime.execution",
            }
        )
        if metadata:
            payload["metadata"] = metadata
        if self._store is not None:
            try:
                self._store.save_outcome(payload)
            except Exception:
                pass
        return payload

    def record_user_outcome(
        self,
        trajectory_id: str | None = None,
        *,
        decision_observation_id: str | None = None,
        feedback_type: UserFeedbackType | None = None,
        rating: float | None = None,
        correction_text: str | None = None,
        confidence: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record a user outcome signal.

        Returns the recorded dict so callers can attach it to observability
        events or API responses.
        """
        ctx = get_observability_context()
        user = UserOutcome(
            feedback_type=feedback_type,
            rating=rating,
            correction_text=correction_text,
            confidence=confidence,
        )
        payload = user.to_dict()
        payload.update(
            {
                "outcome_id": f"out_{uuid.uuid4().hex}",
                "trajectory_id": trajectory_id,
                "decision_observation_id": decision_observation_id,
                "request_id": ctx.request_id,
                "correlation_id": ctx.correlation_id,
                "tenant_id": ctx.tenant_id,
                "user_id": ctx.user_id,
                "session_id": ctx.session_id,
                "conversation_id": ctx.conversation_id,
                "recorded_at": datetime.utcnow().isoformat(),
                "source": "user.feedback",
            }
        )
        if metadata:
            payload["metadata"] = metadata
        if self._store is not None:
            try:
                self._store.save_outcome(payload)
            except Exception:
                pass
        return payload
