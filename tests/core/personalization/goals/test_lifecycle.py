"""Goal-domain contracts and canonical durable lifecycle rules."""

from __future__ import annotations

from datetime import datetime, timedelta

from ai_karen_engine.core.memory.user_state_lifecycle import (
    ProspectiveItemState,
    UserGoalState,
    can_transition_goal,
    can_transition_prospective,
)
from ai_karen_engine.core.personalization.contracts import (
    PreferenceScope,
    UserGoal,
    UserGoalStatus,
)
from ai_karen_engine.core.personalization.goals.conflicts import ConflictDetector
from ai_karen_engine.core.personalization.goals.contracts import (
    ConflictSeverity,
    ConflictType,
    Goal,
    GoalOrigin,
    GoalPriority,
    GoalProgress,
    GoalState,
    GoalType,
    goal_from_user_goal,
    to_snapshot,
)
from ai_karen_engine.core.personalization.goals.prioritization import GoalPrioritizer


def make_goal(
    goal_id: str = "g1",
    *,
    state: GoalState = GoalState.ACTIVE,
    priority: GoalPriority = GoalPriority.MEDIUM,
    tenant_id: str = "t1",
    user_id: str = "u1",
    description: str = "test goal",
) -> Goal:
    return Goal(
        goal_id=goal_id,
        tenant_id=tenant_id,
        user_id=user_id,
        description=description,
        goal_type=GoalType.EXPLICIT,
        origin=GoalOrigin.USER_STATED,
        state=state,
        priority=priority,
        scope=PreferenceScope.GLOBAL,
        confidence=0.8,
        evidence_refs=[],
        started_at=datetime.utcnow(),
        last_observed_at=datetime.utcnow(),
    )


def test_goal_contract_conversion_preserves_explicit_user_goal() -> None:
    user_goal = UserGoal(
        goal_id="g1",
        user_id="u1",
        tenant_id="t1",
        description="ship feature",
        scope=PreferenceScope.GLOBAL,
        status=UserGoalStatus.ACTIVE,
        confidence=0.9,
        evidence=["ev1"],
        started_at=datetime.utcnow(),
        last_observed_at=datetime.utcnow(),
    )

    goal = goal_from_user_goal(user_goal)

    assert goal.goal_type == GoalType.EXPLICIT
    assert goal.origin == GoalOrigin.USER_STATED
    assert goal.state == GoalState.ACTIVE
    assert goal.confidence == 0.9


def test_goal_snapshot_is_read_only_projection() -> None:
    goal = make_goal(goal_id="g-snap")
    snapshot = to_snapshot(goal)

    assert snapshot.goal_id == goal.goal_id
    assert snapshot.description == goal.description
    assert snapshot.state == goal.state


def test_canonical_goal_transition_rules_cover_terminal_user_outcomes() -> None:
    assert can_transition_goal(UserGoalState.ACTIVE.value, UserGoalState.COMPLETED.value)
    assert can_transition_goal(UserGoalState.ACTIVE.value, UserGoalState.ABANDONED.value)
    assert can_transition_goal(UserGoalState.ACTIVE.value, UserGoalState.SUPERSEDED.value)
    assert not can_transition_goal(
        UserGoalState.COMPLETED.value,
        UserGoalState.ACTIVE.value,
    )


def test_canonical_prospective_transition_rules_are_monotonic() -> None:
    assert can_transition_prospective(
        ProspectiveItemState.DORMANT.value,
        ProspectiveItemState.TRIGGERED.value,
    )
    assert can_transition_prospective(
        ProspectiveItemState.DORMANT.value,
        ProspectiveItemState.CANCELLED.value,
    )
    assert can_transition_prospective(
        ProspectiveItemState.COMPLETED.value,
        ProspectiveItemState.ARCHIVED.value,
    )
    assert not can_transition_prospective(
        ProspectiveItemState.ARCHIVED.value,
        ProspectiveItemState.DORMANT.value,
    )


def test_goal_prioritizer_keeps_active_over_paused() -> None:
    prioritizer = GoalPrioritizer()
    active = make_goal(goal_id="active", state=GoalState.ACTIVE)
    paused = make_goal(goal_id="paused", state=GoalState.PAUSED)

    selected = prioritizer.select_active([active, paused])

    assert active in selected
    assert paused not in selected


def test_critical_goal_scores_higher_than_low_priority_goal() -> None:
    prioritizer = GoalPrioritizer()
    critical = make_goal(goal_id="critical", priority=GoalPriority.CRITICAL)
    low = make_goal(goal_id="low", priority=GoalPriority.LOW)

    assert prioritizer.assess(critical).score > prioritizer.assess(low).score


def test_near_term_goal_priority_remains_visible() -> None:
    prioritizer = GoalPrioritizer()
    goal = make_goal(goal_id="urgent", priority=GoalPriority.HIGH)
    goal.target_date = datetime.utcnow() + timedelta(hours=1)
    assessment = prioritizer.assess(goal)

    assert assessment.score >= 0.0
    assert assessment.reason_codes


def test_goal_conflict_detector_preserves_value_conflict_semantics() -> None:
    detector = ConflictDetector()
    local_goal = make_goal(
        goal_id="local",
        description="remain local-first",
    )
    local_goal.conflicts_with = ["cloud"]
    cloud_goal = make_goal(
        goal_id="cloud",
        description="use cloud-only capability",
    )
    cloud_goal.conflicts_with = ["local"]

    conflicts = detector.detect_conflicts([local_goal, cloud_goal])

    value_conflicts = [
        conflict
        for conflict in conflicts
        if conflict.conflict_type == ConflictType.VALUE
    ]
    assert value_conflicts
    assert value_conflicts[0].severity == ConflictSeverity.CRITICAL


def test_goal_progress_contract_remains_available_for_derived_views() -> None:
    progress = GoalProgress(
        completed_steps=1,
        total_steps=4,
        percentage=0.25,
        last_updated=datetime.utcnow(),
    )

    assert progress.completed_steps == 1
    assert progress.total_steps == 4
    assert progress.percentage == 0.25
