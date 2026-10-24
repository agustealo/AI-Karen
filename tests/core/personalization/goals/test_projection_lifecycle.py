"""Canonical goal lifecycle projection must preserve persisted truth."""

import pytest

from ai_karen_engine.core.memory.contracts import GoalState
from ai_karen_engine.platform.personalization.repository import (
    PostgresPersonalizationRepository,
)


@pytest.mark.parametrize("state", list(GoalState))
def test_all_persisted_goal_states_survive_projection(state: GoalState) -> None:
    assert PostgresPersonalizationRepository._goal_status(state.value) is state


@pytest.mark.parametrize("invalid", ["", "unknown", "future_goal_state"])
def test_invalid_persisted_goal_status_fails_closed(invalid: str) -> None:
    with pytest.raises(ValueError, match="Unsupported persisted goal lifecycle state"):
        PostgresPersonalizationRepository._goal_status(invalid)
