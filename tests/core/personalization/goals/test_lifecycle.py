"""
Tests for COG-GOAL-1 goal lifecycle, prioritization, conflicts, and prospective memory.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

import pytest

from ai_karen_engine.core.personalization.goals.contracts import (
    Commitment,
    CommitmentCondition,
    CommitmentEvidence,
    CommitmentParty,
    CommitmentSource,
    CommitmentStrength,
    CommitmentStatus,
    CompletionEvidenceSource,
    ConflictSeverity,
    ConflictType,
    Goal,
    GoalConflict,
    GoalOrigin,
    GoalPriority,
    GoalPriorityAssessment,
    GoalProgress,
    GoalRevision,
    GoalSnapshot,
    GoalState,
    GoalType,
    Intention,
    IntentionEvidence,
    IntentionPriority,
    IntentionState,
    IntentionTriggerType,
    ProspectiveMemory,
    ProspectiveState,
    ProspectiveTrigger,
    goal_from_user_goal,
    to_snapshot,
)
from ai_karen_engine.core.personalization.goals.conflicts import ConflictDetector
from ai_karen_engine.core.personalization.goals.lifecycle import GoalLifecycle
from ai_karen_engine.core.personalization.goals.prioritization import GoalPrioritizer
from ai_karen_engine.core.personalization.goals.prospective import (
    CommitmentLifecycle,
    IntentionLifecycle,
    ProspectiveMemoryManager,
    make_commitment_evidence,
    make_commitment_id,
    make_intention_id,
    make_pm_id,
)
from ai_karen_engine.core.personalization.contracts import (
    PreferenceScope,
    UserGoal,
    UserGoalStatus,
)


def make_goal(
    goal_id: str = "g1",
    state: GoalState = GoalState.ACTIVE,
    goal_type: GoalType = GoalType.EXPLICIT,
    origin: GoalOrigin = GoalOrigin.USER_STATED,
    priority: GoalPriority = GoalPriority.MEDIUM,
    tenant_id: str = "t1",
    user_id: str = "u1",
    target_date: datetime | None = None,
    expires_at: datetime | None = None,
    confidence: float = 0.8,
    description: str = "test goal",
    **kwargs: Any,
) -> Goal:
    return Goal(
        goal_id=goal_id,
        tenant_id=tenant_id,
        user_id=user_id,
        description=description,
        goal_type=goal_type,
        origin=origin,
        state=state,
        priority=priority,
        scope=PreferenceScope.GLOBAL,
        confidence=confidence,
        evidence_refs=[],
        started_at=datetime.utcnow(),
        last_observed_at=datetime.utcnow(),
        target_date=target_date,
        expires_at=expires_at,
        **kwargs,
    )


class TestGoalContracts:
    def test_goal_confidence_clamped(self):
        goal = make_goal(confidence=2.5)
        assert goal.confidence == 1.0

    def test_goal_evidence_confidence_clamped(self):
        from ai_karen_engine.core.personalization.goals.contracts import (
            EvidenceSourceType,
            GoalEvidence,
        )
        ev = GoalEvidence(
            evidence_id="ev1",
            claim="user stated",
            source_type=EvidenceSourceType.USER_STATEMENT,
            source_ref="msg1",
            observed_value="concise",
            polarity="positive",
            confidence=2.0,
            observed_at=datetime.utcnow(),
            tenant_id="t1",
        )
        assert ev.confidence == 1.0

    def test_goal_from_user_goal_explicit_preserves_confidence(self):
        ug = UserGoal(
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
        goal = goal_from_user_goal(ug)
        assert goal.goal_type == GoalType.EXPLICIT
        assert goal.confidence == 0.9
        assert goal.state == GoalState.ACTIVE

    def test_goal_from_user_goal_inferred_lowers_confidence(self):
        ug = UserGoal(
            goal_id="g2",
            user_id="u1",
            tenant_id="t1",
            description="use cloud",
            scope=PreferenceScope.GLOBAL,
            status=UserGoalStatus.ACTIVE,
            confidence=0.9,
            evidence=["ev1"],
            started_at=datetime.utcnow(),
            last_observed_at=datetime.utcnow(),
            metadata={"source": "observation"},
        )
        goal = goal_from_user_goal(ug)
        assert goal.goal_type == GoalType.INFERRED
        assert goal.confidence <= 0.6

    def test_to_snapshot_is_read_only_view(self):
        goal = make_goal(goal_id="g-snap", state=GoalState.ACTIVE)
        snap = to_snapshot(goal)
        assert isinstance(snap, GoalSnapshot)
        assert snap.goal_id == "g-snap"
        assert snap.state == GoalState.ACTIVE
        assert goal.description == snap.description


class TestGoalLifecycle:
    def test_explicit_goal_can_become_active(self):
        lifecycle = GoalLifecycle()
        goal = make_goal(goal_id="g-active", state=GoalState.PROPOSED)
        lifecycle.upsert(goal)
        lifecycle.transition(goal, GoalState.ACTIVE, "approved")
        assert goal.state == GoalState.ACTIVE
        assert len(goal.revisions) == 1

    def test_dependency_can_block_activation(self):
        lifecycle = GoalLifecycle()
        dep = make_goal(goal_id="dep", state=GoalState.ACTIVE)
        blocked = make_goal(goal_id="blocked", state=GoalState.PROPOSED)
        blocked.depends_on.append(dep.goal_id)
        lifecycle.upsert(dep)
        lifecycle.upsert(blocked)
        lifecycle.transition(blocked, GoalState.ACTIVE, "trying to activate")
        all_goals = {"dep": dep, "blocked": blocked}
        result = lifecycle.check_dependencies(blocked, all_goals)
        assert result.state == GoalState.BLOCKED

    def test_paused_goal_not_selected_as_active(self):
        prioritizer = GoalPrioritizer()
        active = make_goal(goal_id="active", state=GoalState.ACTIVE)
        paused = make_goal(goal_id="paused", state=GoalState.PAUSED)
        selected = prioritizer.select_active([active, paused])
        assert active in selected
        assert paused not in selected

    def test_superseded_goal_remains_traceable(self):
        lifecycle = GoalLifecycle()
        old = make_goal(goal_id="old", state=GoalState.ACTIVE)
        new = make_goal(goal_id="new", state=GoalState.PROPOSED)
        lifecycle.upsert(old)
        lifecycle.upsert(new)
        lifecycle.supersede(old, new.goal_id, "replaced")
        assert old.state == GoalState.SUPERSEDED
        assert old.superseded_by == "new"

    def test_expired_goal_does_not_remain_active(self):
        lifecycle = GoalLifecycle()
        expired = make_goal(
            goal_id="expired",
            state=GoalState.ACTIVE,
            expires_at=datetime.utcnow() - timedelta(hours=1),
        )
        lifecycle.upsert(expired)
        lifecycle.expire_if_needed(expired)
        assert expired.state == GoalState.EXPIRED

    def test_completed_goal_requires_completion_evidence(self):
        lifecycle = GoalLifecycle()
        goal = make_goal(
            goal_id="complete",
            state=GoalState.COMPLETED,
            completion_evidence=[],
        )
        assert lifecycle.require_completion_evidence(goal) is False

        goal2 = make_goal(
            goal_id="complete-ev",
            state=GoalState.COMPLETED,
            completion_evidence=["ev1"],
        )
        assert lifecycle.require_completion_evidence(goal2) is True

    def test_completion_evidence_required_before_complete(self):
        lifecycle = GoalLifecycle()
        goal = make_goal(
            goal_id="needs-evidence",
            state=GoalState.ACTIVE,
            completion_evidence_required=[CompletionEvidenceSource.TEST_PASSED],
        )
        lifecycle.upsert(goal)
        # Not all required evidence present -> satisfied check fails
        assert not lifecycle.check_satisfied(goal)
        # Mark satisfied with proper evidence
        lifecycle.mark_satisfied(goal, "test:passed:1")
        assert goal.state == GoalState.SATISFIED

    def test_tenant_isolation(self):
        lifecycle = GoalLifecycle()
        g1 = make_goal(goal_id="g1", tenant_id="tenant-a", user_id="u1")
        g2 = make_goal(goal_id="g2", tenant_id="tenant-b", user_id="u1")
        lifecycle.upsert(g1)
        lifecycle.upsert(g2)
        user_goals = lifecycle.list_for_user("u1", "tenant-a")
        assert all(g.tenant_id == "tenant-a" for g in user_goals)
        assert len(user_goals) == 1

    def test_child_goal_advances_parent(self):
        lifecycle = GoalLifecycle()
        parent = make_goal(goal_id="parent", state=GoalState.ACTIVE)
        parent.progress = GoalProgress(
            completed_steps=0, total_steps=2, percentage=0.0
        )
        child = make_goal(goal_id="child", state=GoalState.COMPLETED)
        parent.child_goal_ids.append(child.goal_id)
        child.parent_goal_id = parent.goal_id
        lifecycle.upsert(parent)
        lifecycle.upsert(child)
        lifecycle.child_advances_parent(child, parent, progress_increment=0.5)
        assert parent.progress.percentage == 0.5
        assert parent.progress.completed_steps == 1


class TestGoalPrioritization:
    def test_critical_priority_scores_higher(self):
        prioritizer = GoalPrioritizer()
        crit = make_goal(goal_id="crit", priority=GoalPriority.CRITICAL)
        low = make_goal(goal_id="low", priority=GoalPriority.LOW)
        crit_score = prioritizer.assess(crit).score
        low_score = prioritizer.assess(low).score
        assert crit_score > low_score

    def test_inferred_has_lower_default_confidence_signal(self):
        prioritizer = GoalPrioritizer()
        explicit = make_goal(
            goal_id="exp", goal_type=GoalType.EXPLICIT,
            origin=GoalOrigin.USER_STATED, confidence=0.9,
        )
        inferred = make_goal(
            goal_id="inf", goal_type=GoalType.INFERRED,
            origin=GoalOrigin.OBSERVATION, confidence=0.6,
        )
        exp_assessment = prioritizer.assess(explicit)
        inf_assessment = prioritizer.assess(inferred)
        # Inferred should have a reason code noting lower default
        assert "inferred_source_lower_default" in inf_assessment.reason_codes
        assert "inferred_source_lower_default" not in exp_assessment.reason_codes

    def test_reason_codes_are_visible(self):
        prioritizer = GoalPrioritizer()
        goal = make_goal(
            goal_id="urgent",
            priority=GoalPriority.CRITICAL,
            target_date=datetime.utcnow() + timedelta(hours=1),
        )
        assessment = prioritizer.assess(goal)
        assert isinstance(assessment, GoalPriorityAssessment)
        assert assessment.score >= 0.0
        assert len(assessment.reason_codes) > 0


class TestConflictDetection:
    def test_goal_conflict_is_detectable(self):
        detector = ConflictDetector()
        local_goal = make_goal(
            goal_id="local",
            description="remain local-first",
            state=GoalState.ACTIVE,
            conflicts_with=["cloud"],
        )
        cloud_goal = make_goal(
            goal_id="cloud",
            description="use cloud-only capability",
            state=GoalState.ACTIVE,
            conflicts_with=["local"],
        )
        conflicts = detector.detect_conflicts([local_goal, cloud_goal])
        assert len(conflicts) > 0
        value_conflicts = [c for c in conflicts if c.conflict_type == ConflictType.VALUE]
        assert len(value_conflicts) > 0
        assert value_conflicts[0].severity == ConflictSeverity.CRITICAL

    def test_no_conflict_for_independent_goals(self):
        detector = ConflictDetector()
        g1 = make_goal(goal_id="g1", description="write docs", state=GoalState.ACTIVE)
        g2 = make_goal(goal_id="g2", description="run tests", state=GoalState.ACTIVE)
        conflicts = detector.detect_conflicts([g1, g2])
        assert len(conflicts) == 0

    def test_circular_dependency_detected(self):
        detector = ConflictDetector()
        g1 = make_goal(goal_id="g1", state=GoalState.ACTIVE)
        g1.depends_on.append("g2")
        g2 = make_goal(goal_id="g2", state=GoalState.ACTIVE)
        g2.depends_on.append("g1")
        conflicts = detector.detect_conflicts([g1, g2])
        dep_conflicts = [c for c in conflicts if c.conflict_type == ConflictType.DEPENDENCY]
        assert len(dep_conflicts) > 0

    def test_recommend_resolution_returns_candidates(self):
        detector = ConflictDetector()
        conflict = GoalConflict(
            conflict_id="c1",
            goal_a_id="a",
            goal_b_id="b",
            conflict_type=ConflictType.VALUE,
            severity=ConflictSeverity.CRITICAL,
            description="test",
        )
        recommendations = detector.recommend_resolution(conflict)
        assert len(recommendations) > 0


class TestCommitments:
    def test_commitment_requires_stronger_evidence(self):
        lifecycle = CommitmentLifecycle()
        commitment = Commitment(
            commitment_id=make_commitment_id(),
            tenant_id="t1",
            user_id="u1",
            parties=[CommitmentParty.KAREN],
            description="deliver feature X",
            source=CommitmentSource.USER_STATEMENT,
            strength=CommitmentStrength.COMMITTED,
            status=CommitmentStatus.PROPOSED,
            confidence=0.9,
            evidence=[],
        )
        # No evidence -> cannot activate
        assert lifecycle.try_activate(commitment) is False
        assert commitment.status == CommitmentStatus.PROPOSED

        # Add strong evidence
        ev1 = make_commitment_evidence(
            CommitmentSource.USER_STATEMENT, 0.95, CommitmentStrength.COMMITTED,
            source_ref="msg1", tenant_id="t1", user_id="u1",
        )
        ev2 = make_commitment_evidence(
            CommitmentSource.OBSERVATION, 0.85, CommitmentStrength.COMMITTED,
            source_ref="obs1", tenant_id="t1", user_id="u1",
        )
        commitment.evidence.extend([ev1, ev2])
        assert lifecycle.try_activate(commitment) is True
        assert commitment.status == CommitmentStatus.ACTIVE


class TestProspectiveMemory:
    def test_intention_remains_dormant_until_trigger(self):
        pm = ProspectiveMemory(
            pm_id=make_pm_id(),
            description="When CORE-SPLIT-2 is complete, revisit model_runtime.",
            trigger=ProspectiveTrigger(
                trigger_type=IntentionTriggerType.GOAL_STATE_RELEVANT,
                target_ref="core-split-2:completed",
                description="goal state change",
                tenant_id="t1",
                user_id="u1",
            ),
            state=ProspectiveState.DORMANT,
            target_intention_id=None,
            target_goal_id=None,
            tenant_id="t1",
            user_id="u1",
        )
        manager = ProspectiveMemoryManager()
        manager.add(pm)

        # Goal not yet completed -> not triggered
        active_goal = make_goal(goal_id="core-split-2", state=GoalState.ACTIVE)
        results = manager.check_all({}, {"core-split-2": active_goal}, "t1", "u1")
        assert pm.state == ProspectiveState.DORMANT
        assert len(results) == 0

        # Now complete the goal
        active_goal.state = GoalState.COMPLETED
        results = manager.check_all({}, {"core-split-2": active_goal}, "t1", "u1")
        assert pm.state == ProspectiveState.TRIGGERED
        assert len(results) == 1

    def test_intention_lifecycle_transitions(self):
        lifecycle = IntentionLifecycle()
        goal = make_goal(goal_id="g-int", state=GoalState.ACTIVE)
        intention = Intention(
            intention_id=make_intention_id(),
            goal_id=goal.goal_id,
            tenant_id="t1",
            user_id="u1",
            description="revisit model_runtime",
            state=IntentionState.FORMED,
            priority=IntentionPriority.HIGH,
            trigger_type=IntentionTriggerType.GOAL_STATE_RELEVANT,
            trigger_condition="g-int:completed",
            context="memory contracts stabilized",
            confidence=0.8,
        )
        lifecycle.add(intention)
        lifecycle.transition(intention, IntentionState.WAITING, "waiting for trigger")
        assert intention.state == IntentionState.WAITING

        activated = lifecycle.tick({"g-int": goal})
        assert len(activated) == 0  # goal not completed yet

        goal.state = GoalState.COMPLETED
        activated = lifecycle.tick({"g-int": goal})
        assert len(activated) > 0
        assert intention.state == IntentionState.ACTIVE

        lifecycle.fulfill(intention, "evidence:1")
        assert intention.state == IntentionState.FULFILLED


class TestGoalStoreBackwardCompat:
    def test_goal_store_backward_compat(self):
        from ai_karen_engine.core.personalization.goals.contracts import GoalStore
        store = GoalStore()
        goal = UserGoal(
            goal_id="g1",
            user_id="u1",
            tenant_id="t1",
            description="ship",
            scope="global",
            status="active",
            confidence=0.8,
            evidence=[],
            started_at=datetime.utcnow(),
            last_observed_at=datetime.utcnow(),
        )
        store.upsert(goal)
        assert store.get("g1") is goal
        assert len(store.list_active("u1", "t1")) == 1


__all__ = [
    "TestGoalContracts",
    "TestGoalLifecycle",
    "TestGoalPrioritization",
    "TestConflictDetection",
    "TestCommitments",
    "TestProspectiveMemory",
    "TestGoalStoreBackwardCompat",
]
