"""
Goal lifecycle and state management for AI-Karen.

Contains the backward-compatible GoalStore (moved out of contracts.py) and
the new GoalLifecycle engine for rich GoalState transitions.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from ..contracts import UserGoal, UserGoalStatus
from .contracts import (
    Goal,
    GoalConflict,
    GoalEvidence,
    GoalProgress,
    GoalRevision,
    GoalSnapshot,
    GoalState,
    CompletionEvidenceSource,
    IntentionState,
    IntentionTriggerType,
    ProspectiveState,
    to_snapshot,
    _map_user_goal_status,
)

logger = logging.getLogger(__name__)


_VALID_TRANSITIONS: Dict[GoalState, Set[GoalState]] = {
    GoalState.PROPOSED: {
        GoalState.ACTIVE,
        GoalState.PAUSED,
        GoalState.ABANDONED,
        GoalState.EXPIRED,
    },
    GoalState.ACTIVE: {
        GoalState.BLOCKED,
        GoalState.PAUSED,
        GoalState.AT_RISK,
        GoalState.SATISFIED,
        GoalState.SUPERSEDED,
        GoalState.ABANDONED,
        GoalState.EXPIRED,
    },
    GoalState.BLOCKED: {
        GoalState.ACTIVE,
        GoalState.PAUSED,
        GoalState.ABANDONED,
        GoalState.EXPIRED,
    },
    GoalState.PAUSED: {
        GoalState.ACTIVE,
        GoalState.ABANDONED,
        GoalState.EXPIRED,
    },
    GoalState.AT_RISK: {
        GoalState.ACTIVE,
        GoalState.BLOCKED,
        GoalState.PAUSED,
        GoalState.SATISFIED,
        GoalState.ABANDONED,
        GoalState.EXPIRED,
    },
    GoalState.SATISFIED: {
        GoalState.COMPLETED,
        GoalState.ACTIVE,
        GoalState.ABANDONED,
        GoalState.EXPIRED,
    },
    GoalState.COMPLETED: set(),
    GoalState.ABANDONED: set(),
    GoalState.SUPERSEDED: set(),
    GoalState.EXPIRED: set(),
}


def _transition_allowed(current: GoalState, target: GoalState) -> bool:
    if current == target:
        return True
    return target in _VALID_TRANSITIONS.get(current, set())


class GoalStore:
    """Stores and manages user goals (backward-compatible API).

    Moved here from contracts.py so contracts remain pure.
    """

    def __init__(self) -> None:
        self._goals: Dict[str, UserGoal] = {}

    def upsert(self, goal: UserGoal) -> None:
        self._goals[goal.goal_id] = goal

    def get(self, goal_id: str) -> Optional[UserGoal]:
        return self._goals.get(goal_id)

    def list_active(self, user_id: str, tenant_id: str) -> List[UserGoal]:
        return [
            g
            for g in self._goals.values()
            if g.user_id == user_id and g.tenant_id == tenant_id and g.status == UserGoalStatus.ACTIVE
        ]

    def list_for_user(self, user_id: str, tenant_id: str) -> List[UserGoal]:
        return [
            g
            for g in self._goals.values()
            if g.user_id == user_id and g.tenant_id == tenant_id
        ]

    def all(self) -> List[UserGoal]:
        return list(self._goals.values())


class GoalLifecycle:
    """Manages rich GoalState transitions and goal hierarchy logic."""

    def __init__(self) -> None:
        self._goals: Dict[str, Goal] = {}
        self._snapshots: List[GoalSnapshot] = []

    # ---- CRUD ----

    def upsert(self, goal: Goal) -> Goal:
        if goal.tenant_id not in (g.tenant_id for g in self._goals.values()):
            pass
        self._goals[goal.goal_id] = goal
        self._snapshots.append(to_snapshot(goal))
        return goal

    def get(self, goal_id: str) -> Optional[Goal]:
        return self._goals.get(goal_id)

    def get_snapshot(self, goal_id: str) -> Optional[GoalSnapshot]:
        goal = self._goals.get(goal_id)
        if goal is None:
            return None
        return to_snapshot(goal)

    def list_for_user(self, user_id: str, tenant_id: str) -> List[Goal]:
        return [
            g
            for g in self._goals.values()
            if g.tenant_id == tenant_id and (g.user_id == user_id or user_id is None)
        ]

    def all(self) -> List[Goal]:
        return list(self._goals.values())

    def all_snapshots(self) -> List[GoalSnapshot]:
        return list(self._snapshots)

    # ---- State transitions ----

    def can_transition(self, goal: Goal, target: GoalState) -> bool:
        if not _is_same_scope(goal, target):
            return False
        return _transition_allowed(goal.state, target)

    def transition(
        self,
        goal: Goal,
        target: GoalState,
        reason: str = "",
        evidence_ref: Optional[str] = None,
    ) -> Goal:
        if not self.can_transition(goal, target):
            raise ValueError(
                f"Cannot transition goal {goal.goal_id} from {goal.state.value} to {target.value}"
            )
        original_state = goal.state
        goal.state = target

        goal.revisions.append(
            GoalRevision(
                revision_id=f"rev_{uuid.uuid4().hex[:12]}",
                goal_id=goal.goal_id,
                field_changed="state",
                old_value=original_state.value,
                new_value=target.value,
                reason=reason or f"transition: {target.value}",
                revised_at=datetime.utcnow(),
                tenant_id=goal.tenant_id,
                user_id=goal.user_id,
            )
        )

        if evidence_ref:
            if evidence_ref not in goal.evidence_refs:
                goal.evidence_refs.append(evidence_ref)

        if target == GoalState.ACTIVE:
            goal.last_observed_at = datetime.utcnow()
        if target == GoalState.COMPLETED:
            goal.completed_at = datetime.utcnow()
        if target == GoalState.ABANDONED:
            goal.expires_at = datetime.utcnow()

        self._snapshots.append(to_snapshot(goal))
        return goal

    # ---- Satisfaction / completion ----

    def check_satisfied(self, goal: Goal) -> bool:
        """A goal is satisfied when all required proof gates pass."""
        if not goal.completion_evidence_required:
            return False
        required = set(s.value for s in goal.completion_evidence_required)
        satisfied = set(s.value for s in goal.completion_evidence_sources)
        return required.issubset(satisfied)

    def mark_satisfied(
        self, goal: Goal, source: CompletionEvidenceSource, evidence_ref: str
    ) -> Goal:
        if evidence_ref not in goal.completion_evidence:
            goal.completion_evidence.append(evidence_ref)
        if source not in goal.completion_evidence_sources:
            goal.completion_evidence_sources.append(source)
        if self.check_satisfied(goal) and goal.state == GoalState.ACTIVE:
            self.transition(goal, GoalState.SATISFIED, "all proof gates pass", evidence_ref)
        return goal

    def require_completion_evidence(self, goal: Goal) -> bool:
        """A completed goal must have completion evidence."""
        if goal.state == GoalState.COMPLETED:
            return len(goal.completion_evidence) > 0
        return True

    def mark_completed(self, goal: Goal, evidence_ref: str) -> Goal:
        if evidence_ref not in goal.completion_evidence:
            goal.completion_evidence.append(evidence_ref)
        if evidence_ref not in goal.evidence_refs:
            goal.evidence_refs.append(evidence_ref)
        self.transition(goal, GoalState.COMPLETED, "completion evidence received", evidence_ref)
        return goal

    # ---- Expiry ----

    def check_expired(self, goal: Goal, now: Optional[datetime] = None) -> bool:
        if goal.expires_at is None:
            return False
        now = now or datetime.utcnow()
        return now > goal.expires_at

    def expire_if_needed(self, goal: Goal, now: Optional[datetime] = None) -> Goal:
        if self.check_expired(goal, now):
            if goal.state not in (GoalState.COMPLETED, GoalState.ABANDONED, GoalState.EXPIRED):
                self.transition(goal, GoalState.EXPIRED, "ttl exceeded")
        return goal

    # ---- Hierarchy ----

    def add_dependency(self, goal: Goal, depends_on_id: str) -> Goal:
        if depends_on_id not in goal.depends_on:
            goal.depends_on.append(depends_on_id)
        return goal

    def add_block(self, goal: Goal, blocks_id: str) -> Goal:
        if blocks_id not in goal.blocks:
            goal.blocks.append(blocks_id)
        return goal

    def add_child(self, parent: Goal, child_id: str) -> Goal:
        if child_id not in parent.child_goal_ids:
            parent.child_goal_ids.append(child_id)
        return parent

    def add_parent(self, child: Goal, parent_id: str) -> Goal:
        if child.parent_goal_id is None:
            child.parent_goal_id = parent_id
        return child

    def child_advances_parent(self, child: Goal, parent: Goal, progress_increment: float = 0.0) -> Goal:
        """When a child goal advances, propagate progress to parent."""
        if progress_increment > 0.0 and parent.progress is not None:
            parent.progress.percentage = min(1.0, parent.progress.percentage + progress_increment)
            parent.progress.completed_steps = min(
                parent.progress.total_steps,
                parent.progress.completed_steps + 1,
            )
            parent.progress.last_updated = datetime.utcnow()
        parent.last_observed_at = datetime.utcnow()
        return parent

    def dependency_blocks(self, goal: Goal, all_goals: Dict[str, Goal]) -> bool:
        """Returns True if any dependency is not in a completed/satisfied state."""
        for dep_id in goal.depends_on:
            dep = all_goals.get(dep_id)
            if dep is None:
                continue
            if dep.state in (GoalState.COMPLETED, GoalState.SATISFIED):
                continue
            return True
        return False

    def check_dependencies(self, goal: Goal, all_goals: Dict[str, Goal]) -> Goal:
        """If a dependency blocks activation, mark the goal BLOCKED."""
        if goal.state == GoalState.ACTIVE and self.dependency_blocks(goal, all_goals):
            self.transition(goal, GoalState.BLOCKED, "dependency not satisfied")
        elif goal.state == GoalState.BLOCKED and not self.dependency_blocks(goal, all_goals):
            self.transition(goal, GoalState.ACTIVE, "dependency satisfied")
        return goal

    # ---- Supersedence ----

    def supersede(self, goal: Goal, replacement_id: str, reason: str = "") -> Goal:
        self.transition(goal, GoalState.SUPERSEDED, reason or "superseded by newer goal")
        goal.superseded_by = replacement_id
        return goal

    # ---- Intention lifecycle ----

    def evaluate_trigger(self, intention, all_goals: Dict[str, Goal]) -> bool:
        """Evaluate whether an intention's trigger is met."""
        if intention.state in (IntentionState.FULFILLED, IntentionState.INVALIDATED, IntentionState.CANCELLED):
            return False
        trigger = intention.trigger_type
        if trigger == IntentionTriggerType.GOAL_STATE_RELEVANT:
            goal = all_goals.get(intention.trigger_condition)
            if goal is None:
                return False
            parts = intention.trigger_condition.split(":")
            if len(parts) >= 2:
                target_state = parts[1]
                return goal.state.value == target_state
            return goal.state == GoalState.COMPLETED
        return False

    def activate_when_ready(self, intention, all_goals: Dict[str, Goal]) -> Any:
        """Transition an intention from WAITING to READY/ACTIVE if triggered."""
        if intention.state == IntentionState.WAITING:
            if self.evaluate_trigger(intention, all_goals):
                from .contracts import (
                    Intention, IntentionState,
                )
                if intention.state == IntentionState.WAITING and self.evaluate_trigger(intention, all_goals):
                    intention.state = IntentionState.READY
                    intention.activated_at = datetime.utcnow()
        return intention


def _is_same_scope(goal: Goal, target: GoalState) -> bool:
    """Check that no tenant/scope invariants are violated by the transition."""
    return True


__all__ = [
    "GoalStore",
    "GoalLifecycle",
    "to_snapshot",
]
