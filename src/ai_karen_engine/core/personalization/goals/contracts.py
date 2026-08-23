"""
Goal contracts for AI-Karen personalization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..contracts import UserGoal, UserGoalStatus


class GoalStore:
    """Stores and manages user goals."""

    def __init__(self):
        self._goals: Dict[str, UserGoal] = {}

    def upsert(self, goal: UserGoal) -> None:
        self._goals[goal.goal_id] = goal

    def get(self, goal_id: str) -> Optional[UserGoal]:
        return self._goals.get(goal_id)

    def list_active(self, user_id: str, tenant_id: str) -> List[UserGoal]:
        return [
            g for g in self._goals.values()
            if g.user_id == user_id and g.tenant_id == tenant_id and g.status == UserGoalStatus.ACTIVE
        ]

    def list_for_user(self, user_id: str, tenant_id: str) -> List[UserGoal]:
        return [
            g for g in self._goals.values()
            if g.user_id == user_id and g.tenant_id == tenant_id
        ]

    def all(self) -> List[UserGoal]:
        return list(self._goals.values())


__all__ = ["GoalStore"]
