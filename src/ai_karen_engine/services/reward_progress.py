"""Application service for evidence-backed user growth projections."""

from __future__ import annotations

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.intelligence.reward import RewardProgressSnapshot, RewardProjector
from ai_karen_engine.core.runtime.outcome.contracts import UserFeedbackType
from ai_karen_engine.core.runtime.outcome.recorder import OutcomeRecorder
from ai_karen_engine.core.runtime.outcome.store import OutcomeStore, get_outcome_store
from ai_karen_engine.platform.observability.context import (
    CorrelationContext,
    reset_correlation_context,
    set_correlation_context,
)


class RewardProgressError(RuntimeError):
    """Invalid user-scoped progress or feedback request."""


class RewardProgressService:
    def __init__(
        self,
        *,
        store: OutcomeStore | None = None,
        projector: RewardProjector | None = None,
    ) -> None:
        self._store = store or get_outcome_store()
        self._projector = projector or RewardProjector()
        self._recorder = OutcomeRecorder(store=self._store)

    @staticmethod
    def _scope(user: UserData) -> tuple[str, str]:
        tenant_id = str(user.tenant_id or "").strip()
        user_id = str(user.user_id or "").strip()
        if not tenant_id or tenant_id == "default":
            raise RewardProgressError("Explicit tenant scope is required")
        if not user_id:
            raise RewardProgressError("Authenticated user scope is required")
        return tenant_id, user_id

    def snapshot(self, user: UserData, *, limit: int = 500) -> RewardProgressSnapshot:
        tenant_id, user_id = self._scope(user)
        records = self._store.list_for_tenant(
            tenant_id,
            user_id=user_id,
            limit=max(1, min(limit, 1000)),
        )
        return self._projector.project(records)

    def record_feedback(
        self,
        user: UserData,
        *,
        trajectory_id: str,
        feedback_type: str,
        message_id: str | None = None,
    ) -> dict:
        """Append feedback only when the trajectory belongs to this user/tenant."""
        tenant_id, user_id = self._scope(user)
        trajectory = str(trajectory_id or "").strip()
        if not trajectory:
            raise RewardProgressError("trajectory_id is required")

        try:
            normalized_feedback = UserFeedbackType(feedback_type)
        except ValueError as exc:
            raise RewardProgressError("Unsupported feedback type") from exc
        if normalized_feedback not in {
            UserFeedbackType.THUMBS_UP,
            UserFeedbackType.THUMBS_DOWN,
        }:
            raise RewardProgressError("Only thumbs-up/down feedback is supported here")

        records = self._store.get_for_trajectory(
            trajectory,
            tenant_id=tenant_id,
        )
        execution = next(
            (
                record
                for record in records
                if record.get("source") == "runtime.execution"
                and str(record.get("user_id") or "") == user_id
            ),
            None,
        )
        if execution is None:
            raise RewardProgressError("Outcome trajectory not found for authenticated user")

        token = set_correlation_context(
            CorrelationContext(
                request_id=execution.get("request_id"),
                correlation_id=execution.get("correlation_id"),
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=execution.get("session_id"),
                conversation_id=execution.get("conversation_id"),
            )
        )
        try:
            payload = self._recorder.record_user_outcome(
                trajectory_id=trajectory,
                feedback_type=normalized_feedback,
                message_id=message_id,
                confidence=1.0,
                metadata={"interface": "web_ui"},
            )
        finally:
            reset_correlation_context(token)

        if payload.get("outcome_store_status") != "stored":
            raise RuntimeError("Feedback persistence failed")
        return payload


_reward_progress_service: RewardProgressService | None = None


def get_reward_progress_service() -> RewardProgressService:
    global _reward_progress_service
    if _reward_progress_service is None:
        _reward_progress_service = RewardProgressService()
    return _reward_progress_service


__all__ = [
    "RewardProgressError",
    "RewardProgressService",
    "get_reward_progress_service",
]
