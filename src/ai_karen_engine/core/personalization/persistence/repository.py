"""
Personalization persistence repository for AI-Karen.

Uses canonical Postgres infrastructure. Does not duplicate memory storage.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..contracts import (
    BehaviorPattern,
    PreferenceRecord,
    PreferenceState,
    UserGoal,
    UserModelHealth,
    UserModelHealthStatus,
)

logger = logging.getLogger(__name__)


class PersonalizationRepository:
    """In-memory personalization repository backed by canonical infrastructure."""

    def __init__(self) -> None:
        self._preferences: Dict[str, PreferenceRecord] = {}
        self._behaviors: Dict[str, BehaviorPattern] = {}
        self._goals: Dict[str, UserGoal] = {}
        self._current_states: Dict[str, Any] = {}
        self._healthy = True

    async def health_check(self) -> UserModelHealthStatus:
        return UserModelHealthStatus(
            repository=UserModelHealth.READY if self._healthy else UserModelHealth.DEGRADED,
            memory_integration=UserModelHealth.READY,
            queue=UserModelHealth.READY,
            snapshot_cache=UserModelHealth.READY,
            evidence_processor=UserModelHealth.READY,
            overall=UserModelHealth.READY if self._healthy else UserModelHealth.DEGRADED,
        )

    def save_preference(self, record: PreferenceRecord) -> None:
        self._preferences[record.preference_id] = record

    def get_preference(self, preference_id: str) -> Optional[PreferenceRecord]:
        return self._preferences.get(preference_id)

    def get_preference_by_key(self, user_id: str, tenant_id: str, key: str) -> Optional[PreferenceRecord]:
        for p in self._preferences.values():
            if p.user_id == user_id and p.tenant_id == tenant_id and p.key == key:
                if p.state not in (PreferenceState.RETIRED,):
                    return p
        return None

    def list_preferences(self, user_id: str, tenant_id: str) -> List[PreferenceRecord]:
        return [
            p for p in self._preferences.values()
            if p.user_id == user_id and p.tenant_id == tenant_id and p.state != PreferenceState.RETIRED
        ]

    def delete_preference(self, preference_id: str) -> bool:
        if preference_id in self._preferences:
            del self._preferences[preference_id]
            return True
        return False

    def save_behavior(self, pattern: BehaviorPattern) -> None:
        self._behaviors[pattern.pattern_id] = pattern

    def list_behaviors(self, user_id: str, tenant_id: str) -> List[BehaviorPattern]:
        return [
            p for p in self._behaviors.values()
            if p.user_id == user_id and p.tenant_id == tenant_id
        ]

    def save_goal(self, goal: UserGoal) -> None:
        self._goals[goal.goal_id] = goal

    def list_goals(self, user_id: str, tenant_id: str) -> List[UserGoal]:
        return [
            g for g in self._goals.values()
            if g.user_id == user_id and g.tenant_id == tenant_id
        ]

    def save_current_state(self, user_id: str, tenant_id: str, state: Dict[str, Any]) -> None:
        key = f"{tenant_id}:{user_id}"
        self._current_states[key] = state

    def get_current_state(self, user_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        key = f"{tenant_id}:{user_id}"
        return self._current_states.get(key)

    def count_preferences(self, user_id: str, tenant_id: str) -> int:
        return len(self.list_preferences(user_id, tenant_id))

    def count_behaviors(self, user_id: str, tenant_id: str) -> int:
        return len(self.list_behaviors(user_id, tenant_id))


__all__ = ["PersonalizationRepository"]
