"""Canonical contracts for deterministic episodic segmentation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class EpisodeBoundaryReason(str, Enum):
    NEW_SESSION = "new_session"
    SESSION_CHANGED = "session_changed"
    PROJECT_CHANGED = "project_changed"
    GOAL_CHANGED = "goal_changed"
    TIME_GAP = "time_gap"
    PRIOR_OUTCOME_CLOSED = "prior_outcome_closed"
    CORRECTION_ATTACHED = "correction_attached"
    CONTINUATION = "continuation"


@dataclass(frozen=True, slots=True)
class EpisodeObservation:
    tenant_id: str
    user_id: str
    session_id: str
    observed_at: datetime
    text: str
    goal_key: str | None = None
    project_key: str | None = None
    outcome_class: str | None = None
    correction: bool = False
    explicit_completion: bool = False

    def normalized_time(self) -> datetime:
        value = self.observed_at
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class EpisodeFrame:
    episode_group_id: str
    tenant_id: str
    user_id: str
    session_id: str
    started_at: datetime
    updated_at: datetime
    goal_key: str | None = None
    project_key: str | None = None
    last_outcome_class: str | None = None
    last_text: str = ""
    turn_count: int = 0

    @classmethod
    def new(cls, observation: EpisodeObservation) -> "EpisodeFrame":
        now = observation.normalized_time()
        return cls(
            episode_group_id=str(uuid.uuid4()),
            tenant_id=observation.tenant_id,
            user_id=observation.user_id,
            session_id=observation.session_id,
            started_at=now,
            updated_at=now,
            goal_key=observation.goal_key,
            project_key=observation.project_key,
            last_outcome_class=observation.outcome_class,
            last_text=observation.text,
            turn_count=1,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "episode_group_id": self.episode_group_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "goal_key": self.goal_key,
            "project_key": self.project_key,
            "last_outcome_class": self.last_outcome_class,
            "last_text": self.last_text,
            "turn_count": self.turn_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "EpisodeFrame":
        return cls(
            episode_group_id=str(data["episode_group_id"]),
            tenant_id=str(data["tenant_id"]),
            user_id=str(data["user_id"]),
            session_id=str(data["session_id"]),
            started_at=_dt(data["started_at"]),
            updated_at=_dt(data["updated_at"]),
            goal_key=_optional(data.get("goal_key")),
            project_key=_optional(data.get("project_key")),
            last_outcome_class=_optional(data.get("last_outcome_class")),
            last_text=str(data.get("last_text") or ""),
            turn_count=max(0, int(data.get("turn_count") or 0)),
        )


@dataclass(frozen=True, slots=True)
class SegmentationDecision:
    frame: EpisodeFrame
    new_episode: bool
    reason: EpisodeBoundaryReason


def _optional(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _dt(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


__all__ = [
    "EpisodeBoundaryReason",
    "EpisodeFrame",
    "EpisodeObservation",
    "SegmentationDecision",
]
