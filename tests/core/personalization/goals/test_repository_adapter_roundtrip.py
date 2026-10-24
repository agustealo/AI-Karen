"""Persisted canonical goal states retain meaning across the personalization adapter."""

from datetime import datetime, timezone

import pytest

from ai_karen_engine.core.memory.contracts import GoalState
from ai_karen_engine.core.personalization.contracts import PreferenceScope, UserGoal
from ai_karen_engine.core.personalization.goals.contracts import goal_from_user_goal
from ai_karen_engine.platform.personalization.repository import PostgresPersonalizationRepository


@pytest.mark.parametrize("state", list(GoalState))
def test_repository_projection_to_goal_domain_preserves_state(state: GoalState) -> None:
    """Protect the real reader-to-domain transformation from status collapse."""
    now = datetime.now(timezone.utc)
    projected = UserGoal(
        goal_id="goal-1",
        user_id="user-1",
        tenant_id="tenant-1",
        description="Persisted goal",
        scope=PreferenceScope.GLOBAL,
        status=PostgresPersonalizationRepository._goal_status(state.value),
        confidence=1.0,
        evidence=[],
        started_at=now,
        last_observed_at=now,
    )
    canonical = goal_from_user_goal(projected)
    assert canonical.state is state
    assert canonical.tenant_id == projected.tenant_id
    assert canonical.user_id == projected.user_id


def test_unsupported_db_state_fails_before_constructing_domain_goal() -> None:
    with pytest.raises(ValueError, match="Unsupported persisted goal lifecycle state"):
        PostgresPersonalizationRepository._goal_status("unexpected_state")
