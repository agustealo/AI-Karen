"""
Goal conflict detection for AI-Karen.

Pure logic: detects conflicts between goals and recommends resolutions.
CORTEX decides; core detects and recommends.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from .contracts import (
    ConflictSeverity,
    ConflictType,
    Goal,
    GoalConflict,
    GoalState,
)

logger = logging.getLogger(__name__)


class ConflictDetector:
    """Detects conflicts between goals."""

    def __init__(self) -> None:
        self._severity_weights: dict[ConflictType, ConflictSeverity] = {
            ConflictType.DEPENDENCY: ConflictSeverity.HIGH,
            ConflictType.VALUE: ConflictSeverity.CRITICAL,
            ConflictType.SCOPE: ConflictSeverity.MEDIUM,
            ConflictType.TEMPORAL: ConflictSeverity.LOW,
        }

    def detect_conflicts(self, goals: list[Goal]) -> list[GoalConflict]:
        """Detect all conflicts among a set of goals."""
        conflicts: list[GoalConflict] = []
        goals_by_id: dict[str, Goal] = {g.goal_id: g for g in goals}

        for i, goal_a in enumerate(goals):
            for goal_b in goals[i + 1:]:
                detected = self._detect_pairwise(goal_a, goal_b)
                for conflict in detected:
                    if conflict not in conflicts:
                        conflicts.append(conflict)

        for goal in goals:
            dep_conflict = self._check_circular_deps(goal, goals_by_id)
            if dep_conflict:
                conflicts.append(dep_conflict)

        return conflicts

    def _detect_pairwise(self, goal_a: Goal, goal_b: Goal) -> list[GoalConflict]:
        """Detect conflicts between two goals."""
        if goal_a.tenant_id != goal_b.tenant_id:
            return []

        conflicts: list[GoalConflict] = []

        value_conflict = self._check_value_conflict(goal_a, goal_b)
        if value_conflict:
            conflicts.append(value_conflict)

        scope_conflict = self._check_scope_conflict(goal_a, goal_b)
        if scope_conflict:
            conflicts.append(scope_conflict)

        temporal_conflict = self._check_temporal_conflict(goal_a, goal_b)
        if temporal_conflict:
            conflicts.append(temporal_conflict)

        dep_conflict = self._check_dependency_conflict(goal_a, goal_b)
        if dep_conflict:
            conflicts.append(dep_conflict)

        return conflicts

    def _check_value_conflict(self, goal_a: Goal, goal_b: Goal) -> GoalConflict | None:
        """Detect when two goals have directly opposing values."""
        if not goal_a.conflicts_with or not goal_b.conflicts_with:
            both_blocked = (goal_a.target_date is not None and goal_b.target_date is not None)
            if not both_blocked:
                return None

        a_in_b = goal_a.goal_id in goal_b.conflicts_with
        b_in_a = goal_b.goal_id in goal_a.conflicts_with
        if not (a_in_b or b_in_a):
            return None

        desc_a = _normalize_desc(goal_a.description)
        desc_b = _normalize_desc(goal_b.description)
        if _are_opposites(desc_a, desc_b):
            return self._make_conflict(
                goal_a, goal_b, ConflictType.VALUE, ConflictSeverity.CRITICAL,
                f"Value conflict: '{goal_a.description}' vs '{goal_b.description}'",
            )

        return self._make_conflict(
            goal_a, goal_b, ConflictType.VALUE, ConflictSeverity.MEDIUM,
            f"Declared conflict: {goal_a.goal_id} <-> {goal_b.goal_id}",
        )

    def _check_scope_conflict(self, goal_a: Goal, goal_b: Goal) -> GoalConflict | None:
        """Detect scope overlap with incompatible values."""
        if goal_a.scope != goal_b.scope:
            return None
        if not (goal_a.conflicts_with or goal_b.conflicts_with):
            return None
        if goal_a.goal_id in goal_b.conflicts_with:
            return self._make_conflict(
                goal_a, goal_b, ConflictType.SCOPE, ConflictSeverity.MEDIUM,
                f"Scope conflict within {goal_a.scope.value}",
            )
        return None

    def _check_temporal_conflict(self, goal_a: Goal, goal_b: Goal) -> GoalConflict | None:
        """Detect temporal overlap with conflicting deadlines."""
        if goal_a.target_date is None and goal_b.target_date is None:
            return None
        if goal_a.target_date is not None and goal_b.target_date is not None:
            delta = abs((goal_a.target_date - goal_b.target_date).total_seconds())
            if delta <= 3600 and goal_a.goal_id in goal_b.conflicts_with:
                return self._make_conflict(
                    goal_a, goal_b, ConflictType.TEMPORAL, ConflictSeverity.LOW,
                    "Tight scheduling overlap between conflicting goals",
                )
        if (goal_a.target_date is not None and goal_b.target_date is not None
                and goal_a.target_date < goal_b.target_date):
            if goal_a.blocks and any(b in goal_a.blocks for b in [goal_b.goal_id]):
                pass
        return None

    def _check_dependency_conflict(self, goal_a: Goal, goal_b: Goal) -> GoalConflict | None:
        """Detect circular or blocking dependency conflicts."""
        if goal_a.goal_id in goal_b.depends_on and goal_b.goal_id in goal_a.depends_on:
            return self._make_conflict(
                goal_a, goal_b, ConflictType.DEPENDENCY, ConflictSeverity.HIGH,
                "Circular dependency",
            )
        if goal_a.goal_id in goal_b.blocks:
            active_a = goal_a.state == GoalState.ACTIVE
            if goal_b.state == GoalState.ACTIVE and active_a:
                return self._make_conflict(
                    goal_a, goal_b, ConflictType.DEPENDENCY, ConflictSeverity.HIGH,
                    "One goal blocks another that is also active",
                )
        return None

    def _check_circular_deps(self, goal: Goal, all_goals: dict[str, Goal]) -> GoalConflict | None:
        """Detect circular dependency chains."""
        visited: set = set()
        stack: list[str] = [goal.goal_id]

        def dfs(node_id: str, path: set) -> tuple[str, str] | None:
            if node_id in path:
                cycle_start = node_id
                return (cycle_start, node_id)
            if node_id in visited:
                return None
            visited.add(node_id)
            path.add(node_id)
            current = all_goals.get(node_id)
            if current:
                for dep_id in current.depends_on:
                    result = dfs(dep_id, path)
                    if result:
                        return result
            path.discard(node_id)
            return None

        result = dfs(goal.goal_id, set())
        if result:
            other = all_goals.get(result[1], goal)
            return self._make_conflict(
                goal, other, ConflictType.DEPENDENCY, ConflictSeverity.CRITICAL,
                f"Circular dependency chain detected at {result[0]}",
            )
        return None

    def _make_conflict(
        self,
        goal_a: Goal,
        goal_b: Goal,
        conflict_type: ConflictType,
        severity: ConflictSeverity,
        description: str,
    ) -> GoalConflict:
        return GoalConflict(
            conflict_id=f"confl_{uuid.uuid4().hex[:12]}",
            goal_a_id=goal_a.goal_id,
            goal_b_id=goal_b.goal_id,
            conflict_type=conflict_type,
            severity=severity,
            description=description,
            evidence_refs=list(goal_a.evidence_refs) + list(goal_b.evidence_refs),
            detected_at=datetime.utcnow(),
            tenant_id=goal_a.tenant_id,
        )

    def recommend_resolution(self, conflict: GoalConflict) -> list[str]:
        """Recommend resolution candidates (CORTEX decides)."""
        candidates: list[str] = []
        if conflict.severity == ConflictSeverity.CRITICAL:
            candidates.extend(["supersede_lower_priority", "decompose_conflict"])
        elif conflict.severity == ConflictSeverity.HIGH:
            candidates.extend(["reorder_dependencies", "restructure_hierarchy"])
        elif conflict.severity == ConflictSeverity.MEDIUM:
            candidates.append("scope_narrowing")
        else:
            candidates.append("monitor")
        return candidates


def _normalize_desc(desc: str) -> str:
    return desc.strip().lower().rstrip(".")


_OPPOSITE_PAIRS: list[tuple[str, str]] = [
    ("remain local", "use cloud"),
    ("remain local-first", "use cloud-only"),
    ("local first", "cloud only"),
    ("keep simple", "add complexity"),
    ("stay small", "expand"),
]


def _are_opposites(desc_a: str, desc_b: str) -> bool:
    for a_phrase, b_phrase in _OPPOSITE_PAIRS:
        if a_phrase in desc_a and b_phrase in desc_b:
            return True
        if a_phrase in desc_b and b_phrase in desc_a:
            return True
    return False


__all__ = ["ConflictDetector"]
