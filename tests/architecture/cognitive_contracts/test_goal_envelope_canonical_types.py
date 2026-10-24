"""Domain goal and commitment contracts share the canonical lifecycle authority."""

from typing import get_type_hints

from ai_karen_engine.core.memory.contracts import GoalState
from ai_karen_engine.core.personalization.contracts import (
    CommitmentState,
    GoalState as PersonalizationGoalEnvelope,
    UserGoal,
)


def test_stored_personalization_goal_envelopes_use_canonical_state() -> None:
    for contract in (UserGoal, PersonalizationGoalEnvelope, CommitmentState):
        assert get_type_hints(contract)["status"] is GoalState


def test_commitments_default_to_canonical_active_state() -> None:
    assert CommitmentState.__dataclass_fields__["status"].default is GoalState.ACTIVE


def test_historical_goal_state_normalization() -> None:
    from ai_karen_engine.core.personalization.contracts import (
        UserGoalStatus, canonical_goal_status,
    )
    for status in UserGoalStatus:
        expected = GoalState.PROPOSED if status is UserGoalStatus.UNKNOWN else GoalState(status.value)
        assert canonical_goal_status(status) is expected
        assert canonical_goal_status(status.value) is expected


def test_canonical_goal_normalization_rejects_unknown_value() -> None:
    import pytest
    from ai_karen_engine.core.personalization.contracts import canonical_goal_status
    with pytest.raises(ValueError, match="Unsupported persisted goal lifecycle state"):
        canonical_goal_status("not_a_real_status")
