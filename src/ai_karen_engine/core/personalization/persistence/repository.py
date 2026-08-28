"""
Personalization persistence repository for AI-Karen.

The repository is the persistence boundary for derived personalization records.
When a platform repository is supplied, async methods delegate to it through the
adapter. The local dictionaries are an explicit ephemeral cache/test fallback;
they are never presented as durable storage.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..adapters import PersonalizationRepositoryAdapter
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
    """Personalization persistence boundary with explicit async delegation."""

    def __init__(self, platform_repository: Any = None) -> None:
        self._platform_repository = platform_repository
        self._adapter: Optional[PersonalizationRepositoryAdapter] = None
        if platform_repository is not None:
            self._adapter = PersonalizationRepositoryAdapter(platform_repository)

        # Explicit ephemeral fallback/cache. These collections are initialized
        # unconditionally so the test/local path is honest and deterministic.
        self._preferences: Dict[str, PreferenceRecord] = {}
        self._behaviors: Dict[str, BehaviorPattern] = {}
        self._goals: Dict[str, UserGoal] = {}
        self._current_states: Dict[str, Dict[str, Any]] = {}

    @property
    def is_durable(self) -> bool:
        """Whether writes are backed by a configured platform repository."""
        return self._adapter is not None

    def set_platform_repository(self, repository: Any) -> None:
        """Attach the canonical platform persistence implementation."""
        self._platform_repository = repository
        self._adapter = PersonalizationRepositoryAdapter(repository)

    async def health_check(self) -> UserModelHealthStatus:
        """Return evidence-backed health without pretending fallback is durable."""
        if self._adapter is not None:
            try:
                return await self._adapter.health_check()
            except Exception as exc:  # health must degrade honestly, not crash callers
                logger.warning("Personalization platform health check failed: %s", exc)

        return UserModelHealthStatus(
            repository=UserModelHealth.DEGRADED,
            memory_integration=UserModelHealth.DEGRADED,
            queue=UserModelHealth.DEGRADED,
            snapshot_cache=UserModelHealth.DEGRADED,
            evidence_processor=UserModelHealth.DEGRADED,
            overall=UserModelHealth.DEGRADED,
        )

    # ------------------------------------------------------------------
    # Async canonical API used by runtime code.
    # ------------------------------------------------------------------
    async def async_save_preference(self, record: PreferenceRecord) -> None:
        if self._adapter is not None:
            await self._adapter.save_preference(record)
        self._preferences[record.preference_id] = record

    async def async_get_preference(self, preference_id: str) -> Optional[PreferenceRecord]:
        if self._adapter is not None:
            record = await self._adapter.get_preference(preference_id)
            if record is not None:
                self._preferences[record.preference_id] = record
            return record
        return self.get_preference(preference_id)

    async def async_get_preference_by_key(
        self,
        user_id: str,
        tenant_id: str,
        key: str,
    ) -> Optional[PreferenceRecord]:
        if self._adapter is not None:
            record = await self._adapter.get_preference_by_key(user_id, tenant_id, key)
            if record is not None:
                self._preferences[record.preference_id] = record
            return record
        return self.get_preference_by_key(user_id, tenant_id, key)

    async def async_list_preferences(self, user_id: str, tenant_id: str) -> List[PreferenceRecord]:
        if self._adapter is not None:
            records = await self._adapter.list_preferences(user_id, tenant_id)
            for record in records:
                self._preferences[record.preference_id] = record
            return records
        return self.list_preferences(user_id, tenant_id)

    async def async_delete_preference(self, preference_id: str) -> bool:
        if self._adapter is not None:
            deleted = await self._adapter.delete_preference(preference_id)
            if deleted:
                self._preferences.pop(preference_id, None)
            return deleted
        return self.delete_preference(preference_id)

    async def async_save_behavior(self, pattern: BehaviorPattern) -> None:
        if self._adapter is not None:
            await self._adapter.save_behavior(pattern)
        self._behaviors[pattern.pattern_id] = pattern

    async def async_list_behaviors(self, user_id: str, tenant_id: str) -> List[BehaviorPattern]:
        if self._adapter is not None:
            patterns = await self._adapter.list_behaviors(user_id, tenant_id)
            for pattern in patterns:
                self._behaviors[pattern.pattern_id] = pattern
            return patterns
        return self.list_behaviors(user_id, tenant_id)

    async def async_save_goal(self, goal: UserGoal) -> None:
        if self._adapter is not None:
            await self._adapter.save_goal(goal)
        self._goals[goal.goal_id] = goal

    async def async_list_goals(self, user_id: str, tenant_id: str) -> List[UserGoal]:
        if self._adapter is not None:
            goals = await self._adapter.list_goals(user_id, tenant_id)
            for goal in goals:
                self._goals[goal.goal_id] = goal
            return goals
        return self.list_goals(user_id, tenant_id)

    # ------------------------------------------------------------------
    # Synchronous ephemeral compatibility API.
    # It never drives an event loop and therefore cannot deadlock async callers.
    # ------------------------------------------------------------------
    def save_preference(self, record: PreferenceRecord) -> None:
        self._preferences[record.preference_id] = record

    def get_preference(self, preference_id: str) -> Optional[PreferenceRecord]:
        return self._preferences.get(preference_id)

    def get_preference_by_key(
        self,
        user_id: str,
        tenant_id: str,
        key: str,
    ) -> Optional[PreferenceRecord]:
        matches = [
            record
            for record in self._preferences.values()
            if record.user_id == user_id
            and record.tenant_id == tenant_id
            and record.key == key
            and record.state != PreferenceState.RETIRED
        ]
        if not matches:
            return None
        # Deterministic winner: highest version, then most recently observed,
        # then stable ID as a final total-order tie breaker.
        return max(
            matches,
            key=lambda record: (
                record.version,
                record.last_observed_at,
                record.preference_id,
            ),
        )

    def list_preferences(self, user_id: str, tenant_id: str) -> List[PreferenceRecord]:
        return sorted(
            (
                record
                for record in self._preferences.values()
                if record.user_id == user_id
                and record.tenant_id == tenant_id
                and record.state != PreferenceState.RETIRED
            ),
            key=lambda record: (record.key, record.scope.value, record.preference_id),
        )

    def delete_preference(self, preference_id: str) -> bool:
        return self._preferences.pop(preference_id, None) is not None

    def save_behavior(self, pattern: BehaviorPattern) -> None:
        self._behaviors[pattern.pattern_id] = pattern

    def list_behaviors(self, user_id: str, tenant_id: str) -> List[BehaviorPattern]:
        return sorted(
            (
                pattern
                for pattern in self._behaviors.values()
                if pattern.user_id == user_id and pattern.tenant_id == tenant_id
            ),
            key=lambda pattern: (pattern.pattern_type, pattern.context_signature, pattern.pattern_id),
        )

    def save_goal(self, goal: UserGoal) -> None:
        self._goals[goal.goal_id] = goal

    def list_goals(self, user_id: str, tenant_id: str) -> List[UserGoal]:
        return sorted(
            (
                goal
                for goal in self._goals.values()
                if goal.user_id == user_id and goal.tenant_id == tenant_id
            ),
            key=lambda goal: (goal.started_at, goal.goal_id),
        )

    def save_current_state(self, user_id: str, tenant_id: str, state: Dict[str, Any]) -> None:
        """Store ephemeral current state only; this method does not claim durability."""
        self._current_states[self._state_key(user_id, tenant_id)] = dict(state)

    def get_current_state(self, user_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        state = self._current_states.get(self._state_key(user_id, tenant_id))
        return dict(state) if state is not None else None

    def count_preferences(self, user_id: str, tenant_id: str) -> int:
        return len(self.list_preferences(user_id, tenant_id))

    def count_behaviors(self, user_id: str, tenant_id: str) -> int:
        return len(self.list_behaviors(user_id, tenant_id))

    @staticmethod
    def _state_key(user_id: str, tenant_id: str) -> str:
        return f"{tenant_id}:{user_id}"


__all__ = ["PersonalizationRepository"]
