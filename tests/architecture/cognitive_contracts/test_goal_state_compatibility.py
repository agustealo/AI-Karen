"""Protect canonical goal lifecycle semantics during legacy reader migration."""

import pytest

from ai_karen_engine.core.memory.contracts import GoalState
from ai_karen_engine.core.personalization.contracts import UserGoalStatus
from ai_karen_engine.core.personalization.goals.contracts import _map_user_goal_status


@pytest.mark.parametrize("state", list(GoalState))
def test_canonical_goal_state_survives_legacy_adapter(state: GoalState) -> None:
    assert _map_user_goal_status(state) is state
    assert _map_user_goal_status(state.value) is state


@pytest.mark.parametrize(
    ("status", "state"),
    [
        (UserGoalStatus.ACTIVE, GoalState.ACTIVE),
        (UserGoalStatus.PAUSED, GoalState.PAUSED),
        (UserGoalStatus.COMPLETED, GoalState.COMPLETED),
        (UserGoalStatus.ABANDONED, GoalState.ABANDONED),
        (UserGoalStatus.UNKNOWN, GoalState.PROPOSED),
    ],
)
def test_historical_goal_status_semantics_are_preserved(status, state) -> None:
    assert _map_user_goal_status(status) is state
    assert _map_user_goal_status(status.value) is state


@pytest.mark.parametrize("invalid", ["", "unknown_future_state", None, 42, {}, []])
def test_invalid_persisted_state_rejected_without_lifecycle_reset(invalid) -> None:
    with pytest.raises(ValueError, match="Unsupported persisted goal lifecycle state"):
        _map_user_goal_status(invalid)
