from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ai_karen_engine.core.runtime.outcome.contracts import (
    ExecutionOutcome,
    ExecutionStatus,
    UserFeedbackType,
    UserOutcome,
)
from ai_karen_engine.core.runtime.outcome.store import OutcomeStore
from ai_karen_engine.platform.observability.context import (
    get_correlation_context as get_observability_context,
)

logger = logging.getLogger(__name__)


class OutcomeRecorder:
    """Records execution and user outcome facts linked to trajectories.

    This component remains observational. It does not calculate rewards or
    change runtime behavior. Persistence failures are surfaced in returned
    metadata and structured logs rather than silently swallowed.
    """

    def __init__(self, store: OutcomeStore | None = None) -> None:
        self._store = store

    def _persist(self, payload: dict[str, Any]) -> None:
        if self._store is None:
            payload["outcome_store_status"] = "not_configured"
            return
        try:
            self._store.save_outcome(payload)
            payload["outcome_store_status"] = "stored"
        except Exception:
            payload["outcome_store_status"] = "failed"
            payload["outcome_store_error_code"] = "outcome_persistence_failed"
            logger.exception(
                "outcome.recorder.persistence_failed",
                extra={
                    "outcome_id": payload.get("outcome_id"),
                    "tenant_id": payload.get("tenant_id"),
                    "user_id": payload.get("user_id"),
                    "source": payload.get("source"),
                },
            )

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
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "source": "runtime.execution",
            }
        )
        if metadata:
            payload["metadata"] = metadata
        self._persist(payload)
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
        message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
                "message_id": message_id,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "source": "user.feedback",
            }
        )
        if metadata:
            payload["metadata"] = metadata
        self._persist(payload)
        return payload
