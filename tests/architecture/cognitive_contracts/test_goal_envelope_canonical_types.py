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
