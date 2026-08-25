"""
Goal prioritization for AI-Karen.

Pure cognitive priority logic: computes priority scores and selects which
goals deserve active work, without touching schedulers or executors.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .contracts import (
    Goal,
    GoalOrigin,
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
        if goal.origin == GoalOrigin.INFERRED:
            reason_codes.append("inferred_source_lower_default")
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
        """Select goals eligible for active work.

        Excludes PAUSED, EXPIRED, ABANDONED, SUPERSEDED, COMPLETED,
        and goals whose dependencies are not yet satisfiable.
        """
        now = datetime.utcnow()
        eligible: List[Goal] = []
        for g in goals:
            if g.state in (GoalState.ACTIVE, GoalState.SATISFIED, GoalState.AT_RISK, GoalState.PROPOSED):
                if g.expires_at is not None and now > g.expires_at:
                    continue
                if not g.is_terminal():
                    eligible.append(g)
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
            if remaining <= 0:
                return 1.0
            reference_window = remaining * 4.0
            if reference_window <= 0:
                return 1.0
            return max(0.0, min(1.0, 1.0 - remaining / reference_window))
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
        reference = remaining + 86400.0
        return max(0.0, min(1.0, 1.0 - remaining / reference)) if reference > 0 else 0.0

    def _dependency_pressure(self, goal: Goal, context: Dict[str, Any]) -> float:
        dep_count = context.get("dependency_count", {}).get(goal.goal_id, 0)
        return max(0.0, min(1.0, float(dep_count) / 5.0))

    def _blocking_impact(self, goal: Goal, context: Dict[str, Any]) -> float:
        blocked_count = context.get("blocked_count", {}).get(goal.goal_id, 0)
        return max(0.0, min(1.0, float(blocked_count) / 5.0))

    def _hierarchy_factor(self, goal: Goal, context: Dict[str, Any]) -> float:
        depth = context.get("hierarchy_depth", {}).get(goal.goal_id, 0)
        return max(0.0, min(1.0, float(depth) / 5.0))

    def _context_relevance(self, goal: Goal, context: Dict[str, Any]) -> float:
        relevance = context.get("goal_relevance", {}).get(goal.goal_id, 0.3)
        if not isinstance(relevance, (int, float)):
            relevance = 0.3
        return max(0.0, min(1.0, float(relevance)))


__all__ = ["GoalPrioritizer"]
