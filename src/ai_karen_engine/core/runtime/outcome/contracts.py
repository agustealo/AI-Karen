from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ExecutionStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL_SUCCESS = "partial_success"


class UserFeedbackType(str, Enum):
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    RATING = "rating"
    USER_CORRECTION = "user_correction"
    RETRY = "retry"
    REGENERATION = "regeneration"
    CONVERSATION_ABANDONMENT = "conversation_abandonment"
    FOLLOW_UP_CLARIFICATION = "follow_up_clarification"
    TASK_COMPLETION_CONFIRMATION = "task_completion_confirmation"


@dataclass(slots=True)
class ExecutionOutcome:
    """System-observable facts about execution."""

    status: ExecutionStatus = ExecutionStatus.FAILURE
    latency_ms: float | None = None
    provider_errors: list[str] = field(default_factory=list)
    fallback_count: int = 0
    tool_success: bool | None = None
    plugin_success: bool | None = None
    schema_valid: bool | None = None
    response_completed: bool | None = None
    persistence_success: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "latency_ms": self.latency_ms,
            "provider_errors": self.provider_errors,
            "fallback_count": self.fallback_count,
            "tool_success": self.tool_success,
            "plugin_success": self.plugin_success,
            "schema_valid": self.schema_valid,
            "response_completed": self.response_completed,
            "persistence_success": self.persistence_success,
        }


@dataclass(slots=True)
class UserOutcome:
    """User-observed signals about the interaction."""

    feedback_type: UserFeedbackType | None = None
    rating: float | None = None
    correction_text: str | None = None
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.feedback_type is not None:
            data["feedback_type"] = self.feedback_type.value
        if self.rating is not None:
            data["rating"] = self.rating
        if self.correction_text is not None:
            data["correction_text"] = self.correction_text
        if self.confidence is not None:
            data["confidence"] = self.confidence
        return data


@dataclass(slots=True)
class OutcomeRecord:
    """Durable outcome record linked to an execution trajectory.

    Execution outcome and user outcome are stored separately to prevent
    premature scalar reward calculation.
    """

    outcome_id: str
    trajectory_id: str | None = None
    message_id: str | None = None
    conversation_id: str | None = None

    tenant_id: str | None = None
    user_id: str | None = None

    recorded_at: datetime = field(default_factory=datetime.utcnow)

    execution_outcome: ExecutionOutcome = field(default_factory=ExecutionOutcome)
    user_outcome: UserOutcome = field(default_factory=UserOutcome)

    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "outcome_id": self.outcome_id,
            "trajectory_id": self.trajectory_id,
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "recorded_at": self.recorded_at.isoformat(),
            "execution_outcome": self.execution_outcome.to_dict(),
            "user_outcome": self.user_outcome.to_dict(),
            "source": self.source,
        }
        if self.metadata:
            data["metadata"] = self.metadata
        return data
