"""Canonical lifecycle contracts for durable user goals and prospective memory.

These contracts define legal state transitions only. They do not own storage,
timers, reminders, scheduling, or runtime execution.
"""

from __future__ import annotations

from ai_karen_engine.core.memory.contracts import (
    GoalState,
    OpenLoopState,
    ProspectiveState,
)


_GOAL_TRANSITIONS: dict[GoalState, frozenset[GoalState]] = {
    GoalState.ACTIVE: frozenset(
        {
            GoalState.BLOCKED,
            GoalState.PAUSED,
            GoalState.AT_RISK,
            GoalState.SATISFIED,
            GoalState.COMPLETED,
            GoalState.ABANDONED,
            GoalState.SUPERSEDED,
            GoalState.EXPIRED,
        }
    ),
    GoalState.BLOCKED: frozenset(
        {
            GoalState.ACTIVE,
            GoalState.PAUSED,
            GoalState.ABANDONED,
            GoalState.SUPERSEDED,
            GoalState.EXPIRED,
        }
    ),
    GoalState.PAUSED: frozenset(
        {
            GoalState.ACTIVE,
            GoalState.ABANDONED,
            GoalState.SUPERSEDED,
            GoalState.EXPIRED,
        }
    ),
    GoalState.AT_RISK: frozenset(
        {
            GoalState.ACTIVE,
            GoalState.BLOCKED,
            GoalState.PAUSED,
            GoalState.SATISFIED,
            GoalState.COMPLETED,
            GoalState.ABANDONED,
            GoalState.SUPERSEDED,
            GoalState.EXPIRED,
        }
    ),
    GoalState.SATISFIED: frozenset(
        {
            GoalState.COMPLETED,
            GoalState.ACTIVE,
            GoalState.ABANDONED,
            GoalState.EXPIRED,
        }
    ),
    GoalState.COMPLETED: frozenset(),
    GoalState.ABANDONED: frozenset(),
    GoalState.SUPERSEDED: frozenset(),
    GoalState.EXPIRED: frozenset(),
}

_PROSPECTIVE_TRANSITIONS: dict[
    ProspectiveState,
    frozenset[ProspectiveState],
] = {
    ProspectiveState.DORMANT: frozenset(
        {
            ProspectiveState.READY,
            ProspectiveState.TRIGGERED,
            ProspectiveState.COMPLETED,
            ProspectiveState.CANCELLED,
            ProspectiveState.SUPERSEDED,
            ProspectiveState.ARCHIVED,
        }
    ),
    ProspectiveState.READY: frozenset(
        {
            ProspectiveState.TRIGGERED,
            ProspectiveState.COMPLETED,
            ProspectiveState.CANCELLED,
            ProspectiveState.ARCHIVED,
        }
    ),
    ProspectiveState.TRIGGERED: frozenset(
        {
            ProspectiveState.COMPLETED,
            ProspectiveState.CANCELLED,
            ProspectiveState.ARCHIVED,
        }
    ),
    ProspectiveState.COMPLETED: frozenset({ProspectiveState.ARCHIVED}),
    ProspectiveState.CANCELLED: frozenset({ProspectiveState.ARCHIVED}),
    ProspectiveState.SUPERSEDED: frozenset({ProspectiveState.ARCHIVED}),
    ProspectiveState.ARCHIVED: frozenset(),
}


def can_transition_goal(current: str, target: str) -> bool:
    try:
        current_state = GoalState(current)
        target_state = GoalState(target)
    except ValueError:
        return False
    return current_state == target_state or target_state in _GOAL_TRANSITIONS[current_state]


_OPEN_LOOP_TRANSITIONS: dict[OpenLoopState, frozenset[OpenLoopState]] = {
    OpenLoopState.OPEN: frozenset(
        {
            OpenLoopState.COMPLETED,
            OpenLoopState.CANCELLED,
            OpenLoopState.SUPERSEDED,
        }
    ),
    OpenLoopState.COMPLETED: frozenset(),
    OpenLoopState.CANCELLED: frozenset(),
    OpenLoopState.SUPERSEDED: frozenset(),
}


def can_transition_prospective(current: str, target: str) -> bool:
    try:
        current_state = ProspectiveState(current)
        target_state = ProspectiveState(target)
    except ValueError:
        return False
    return (
        current_state == target_state
        or target_state in _PROSPECTIVE_TRANSITIONS[current_state]
    )


def can_transition_open_loop(current: str, target: str) -> bool:
    try:
        current_state = OpenLoopState(current)
        target_state = OpenLoopState(target)
    except ValueError:
        return False
    return (
        current_state == target_state
        or target_state in _OPEN_LOOP_TRANSITIONS[current_state]
    )


__all__ = [
    "GoalState",
    "OpenLoopState",
    "ProspectiveState",
    "can_transition_goal",
    "can_transition_open_loop",
    "can_transition_prospective",
]
