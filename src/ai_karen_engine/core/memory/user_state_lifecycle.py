"""Canonical lifecycle contracts for durable user goals and prospective memory.

These contracts define legal state transitions only. They do not own storage,
timers, reminders, scheduling, or runtime execution.
"""

from __future__ import annotations

from enum import Enum


class UserGoalState(str, Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    PAUSED = "paused"
    AT_RISK = "at_risk"
    SATISFIED = "satisfied"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


class ProspectiveItemState(str, Enum):
    DORMANT = "dormant"
    READY = "ready"
    TRIGGERED = "triggered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


_GOAL_TRANSITIONS: dict[UserGoalState, frozenset[UserGoalState]] = {
    UserGoalState.ACTIVE: frozenset(
        {
            UserGoalState.BLOCKED,
            UserGoalState.PAUSED,
            UserGoalState.AT_RISK,
            UserGoalState.SATISFIED,
            UserGoalState.COMPLETED,
            UserGoalState.ABANDONED,
            UserGoalState.SUPERSEDED,
            UserGoalState.EXPIRED,
        }
    ),
    UserGoalState.BLOCKED: frozenset(
        {
            UserGoalState.ACTIVE,
            UserGoalState.PAUSED,
            UserGoalState.ABANDONED,
            UserGoalState.SUPERSEDED,
            UserGoalState.EXPIRED,
        }
    ),
    UserGoalState.PAUSED: frozenset(
        {
            UserGoalState.ACTIVE,
            UserGoalState.ABANDONED,
            UserGoalState.SUPERSEDED,
            UserGoalState.EXPIRED,
        }
    ),
    UserGoalState.AT_RISK: frozenset(
        {
            UserGoalState.ACTIVE,
            UserGoalState.BLOCKED,
            UserGoalState.PAUSED,
            UserGoalState.SATISFIED,
            UserGoalState.COMPLETED,
            UserGoalState.ABANDONED,
            UserGoalState.SUPERSEDED,
            UserGoalState.EXPIRED,
        }
    ),
    UserGoalState.SATISFIED: frozenset(
        {
            UserGoalState.COMPLETED,
            UserGoalState.ACTIVE,
            UserGoalState.ABANDONED,
            UserGoalState.EXPIRED,
        }
    ),
    UserGoalState.COMPLETED: frozenset(),
    UserGoalState.ABANDONED: frozenset(),
    UserGoalState.SUPERSEDED: frozenset(),
    UserGoalState.EXPIRED: frozenset(),
}

_PROSPECTIVE_TRANSITIONS: dict[
    ProspectiveItemState,
    frozenset[ProspectiveItemState],
] = {
    ProspectiveItemState.DORMANT: frozenset(
        {
            ProspectiveItemState.READY,
            ProspectiveItemState.TRIGGERED,
            ProspectiveItemState.COMPLETED,
            ProspectiveItemState.CANCELLED,
            ProspectiveItemState.SUPERSEDED,
            ProspectiveItemState.ARCHIVED,
        }
    ),
    ProspectiveItemState.READY: frozenset(
        {
            ProspectiveItemState.TRIGGERED,
            ProspectiveItemState.COMPLETED,
            ProspectiveItemState.CANCELLED,
            ProspectiveItemState.ARCHIVED,
        }
    ),
    ProspectiveItemState.TRIGGERED: frozenset(
        {
            ProspectiveItemState.COMPLETED,
            ProspectiveItemState.CANCELLED,
            ProspectiveItemState.ARCHIVED,
        }
    ),
    ProspectiveItemState.COMPLETED: frozenset({ProspectiveItemState.ARCHIVED}),
    ProspectiveItemState.CANCELLED: frozenset({ProspectiveItemState.ARCHIVED}),
    ProspectiveItemState.SUPERSEDED: frozenset({ProspectiveItemState.ARCHIVED}),
    ProspectiveItemState.ARCHIVED: frozenset(),
}


def can_transition_goal(current: str, target: str) -> bool:
    try:
        current_state = UserGoalState(current)
        target_state = UserGoalState(target)
    except ValueError:
        return False
    return current_state == target_state or target_state in _GOAL_TRANSITIONS[current_state]


def can_transition_prospective(current: str, target: str) -> bool:
    try:
        current_state = ProspectiveItemState(current)
        target_state = ProspectiveItemState(target)
    except ValueError:
        return False
    return (
        current_state == target_state
        or target_state in _PROSPECTIVE_TRANSITIONS[current_state]
    )


__all__ = [
    "ProspectiveItemState",
    "UserGoalState",
    "can_transition_goal",
    "can_transition_prospective",
]
