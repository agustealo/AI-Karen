"""
Goal prioritization for AI-Karen.

Pure cognitive priority logic: computes priority scores and selects which
goals deserve active work, without touching schedulers or executors.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from .contracts import (
    Goal,
    GoalPriority,
    GoalPriorityAssessment,
    GoalState,
    GoalSnapshot,
    to_snapshot,
)

logger = logging.getLogger(__name__)


class GoalPrioritizer:
    """Computes cognitive priority for goals."""

    def __init__(self) -> None:
        self._weights: Dict[str, float] = {
            "explicit_priority": 0.25,
            "urgency": 0.20,
            "importance": 0.15,
            "deadline_relevance": 0.15,
            "dependency_pressure": 0.10,
            "blocking_impact": 0.08,
            "hierarchy_depth": 0.04,
            "context_relevance": 0.03,
        }
        self._priority_values: Dict[GoalPriority, float] = {
            GoalPriority.LOW: 0.25,
            GoalPriority.MEDIUM: 0.5,
            GoalPriority.HIGH: 0.75,
            GoalPriority.CRITICAL: 1.0,
        }

    def assess(self, goal: Goal, context: Optional[Dict[str, Any]] = None) -> GoalPriorityAssessment:
        """Compute a priority assessment for a single goal."""
        context = context or {}
        reason_codes: List[str] = []
        evidence_refs: List[str] = list(goal.evidence_refs)

        explicit = self._priority_from_explicit(goal)
        urgency = self._urgency_score(goal, context)
        importance = self._importance_score(goal, context)
        deadline = self._deadline_relevance(goal)
        dep_pressure = self._dependency_pressure(goal, context)
        blocking = self._blocking_impact(goal, context)
        hierarchy = self._hierarchy_factor(goal, context)
        context_rel = self._context_relevance(goal, context)

        score = (
            self._weights["explicit_priority"] * explicit
            + self._weights["urgency"] * urgency
            + self._weights["importance"] * importance
            + self._weights["deadline_relevance"] * deadline
            + self._weights["dependency_pressure"] * dep_pressure
            + self._weights["blocking_impact"] * blocking
            + self._weights["hierarchy_depth"] * hierarchy
            + self._weights["context_relevance"] * context_rel
        )
        score = max(0.0, min(1.0, score))

        if goal.goal_type.value == GoalPriority.CRITICAL.value:
            pass
        if explicit >= 0.9:
            reason_codes.append("critical_priority")
        if urgency >= 0.8:
            reason_codes.append("urgent")
        if deadline >= 0.8:
            reason_codes.append("near_deadline")
        if dep_pressure >= 0.7:
            reason_codes.append("dependency_pressure")
        if blocking >= 0.7:
            reason_codes.append("blocking_impact")
        if goal.origin.value == GoalOrigin.INFERRED.value if False else False:
            pass
        if not reason_codes:
            reason_codes.append("baseline")

        if goal.evidence:
            evidence_refs.extend(e.evidence_id for e in goal.evidence)

        return GoalPriorityAssessment(
            goal_id=goal.goal_id,
            score=score,
            reason_codes=reason_codes,
            evidence_refs=evidence_refs[:20],
            assessed_at=datetime.utcnow(),
        )

    def select_active(
        self,
        goals: List[Goal],
        context: Optional[Dict[str, Any]] = None,
        top_k: int = 5,
    ) -> List[Goal]:
        """Select goals that are eligible for active work.

        Excludes PAUSED, EXPIRED, ABANDONED, SUPERSEDED, COMPLETED,
        and BLOCKED goals that cannot yet proceed.
        """
        eligible = [
            g for g in goals
            if g.state in (GoalState.ACTIVE, GoalState.SATISFIED, GoalState.AT_RISK, GoalState.PROPOSED)
            and g.state != GoalState.PAUSED
            and not (g.expires_at is not None and datetime.utcnow() > g.expires_at)
            and not g.is_terminal()
        ]
        assessed = [(g, self.assess(g, context)) for g in eligible]
        assessed.sort(key=lambda pair: pair[1].score, reverse=True)
        return [g for g, _ in assessed[:top_k]]

    def rank(
        self,
        goals: List[Goal],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[GoalPriorityAssessment]:
        """Rank all goals by priority assessment."""
        results = [self.assess(g, context) for g in goals]
        results.sort(key=lambda a: a.score, reverse=True)
        return results

    def to_snapshots(self, goals: List[Goal]) -> List[GoalSnapshot]:
        return [to_snapshot(g) for g in goals]

    # ---- private helpers ----

    def _priority_from_explicit(self, goal: Goal) -> float:
        return self._priority_values.get(goal.priority, 0.5)

    def _urgency_score(self, goal: Goal, context: Dict[str, Any]) -> float:
        now = datetime.utcnow()
        if goal.target_date is not None:
            remaining = (goal.target_date - now).total_seconds()
            total_span = max(1.0, remaining + 1.0)
            urgency = max(0.0, min(1.0, 1.0 - remaining / (remaining + abs(total_span))))
            return urgency
        explicit_urgency = context.get("explicit_urgency", 0.0)
        if isinstance(explicit_urgency, (int, float)):
            return max(0.0, min(1.0, float(explicit_urgency)))
        return 0.3

    def _importance_score(self, goal: Goal, context: Dict[str, Any]) -> float:
        importance = context.get("goal_importance", {}).get(goal.goal_id, 0.5)
        if not isinstance(importance, (int, float)):
            importance = 0.5
        return max(0.0, min(1.0, float(importance)))

    def _deadline_relevance(self, goal: Goal) -> float:
        if goal.target_date is None:
            return 0.0
        now = datetime.utcnow()
        remaining = (goal.target_date - now).total_seconds()
        if remaining <= 0:
            return 0.0
        max_seconds = context_max_deadline := remaining + 86400.0
        return max(0.0, min(1.0, 1.0 - remaining / max_seconds)) if max_seconds > 0 else 0.0

    def _dependency_pressure(self, goal: Goal, context: Dict[str, Any]) -> float:
        dep_count = context.get("dependency_count", {}).get(goal.goal_id, 0)
        return max(0.0, min(1.0, dep_count / 5.0))

    def _blocking_impact(self, goal: Goal, context: Dict[str, Any]) -> float:
        blocked_count = context.get("blocked_count", {}).get(goal.goal_id, 0)
        return max(0.0, min(1.0, blocked_count / 5.0))

    def _hierarchy_factor(self, goal: Goal, context: Dict[str, Any]) -> float:
        depth = context.get("hierarchy_depth", {}).get(goal.goal_id, 0)
        return max(0.0, min(1.0, depth / 5.0))

    def _context_relevance(self, goal: Goal, context: Dict[str, Any]) -> float:
        relevance = context.get("goal_relevance", {}).get(goal.goal_id, 0.3)
        if not isinstance(relevance, (int, float)):
            relevance = 0.3
        return max(0.0, min(1.0, float(relevance)))


from .contracts import GoalOrigin  # noqa: E402


__all__ = ["GoalPrioritizer"]
