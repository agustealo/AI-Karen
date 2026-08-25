"""
Personalization persistence repository for AI-Karen.

Uses platform persistence via adapter pattern.
Core must not directly depend on platform implementations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..contracts import (
    BehaviorPattern,
    PreferenceRecord,
    PreferenceState,
    UserGoal,
    UserModelHealth,
    UserModelHealthStatus,
)
from ..adapters import PersonalizationRepositoryAdapter

logger = logging.getLogger(__name__)


class PersonalizationRepository:
    """Personalization repository backed by platform persistence."""

    def __init__(self, platform_repository=None):
        self._platform_repository = platform_repository
        self._adapter = None
        if platform_repository is not None:
            self._adapter = PersonalizationRepositoryAdapter(platform_repository)

    def set_platform_repository(self, repository) -> None:
        """Set the platform repository (CORE-SPLIT-2 migration)."""
        self._platform_repository = repository
        self._adapter = PersonalizationRepositoryAdapter(repository)

    async def health_check(self) -> UserModelHealthStatus:
        """Evidence-backed health check."""
        if self._adapter is not None:
            try:
                return await self._adapter.health_check()
            except Exception as exc:
                logger.debug("Platform health check failed: %s", exc)

        # Fallback: honest degraded state instead of fake health
        return UserModelHealthStatus(
            repository=UserModelHealth.DEGRADED,
            memory_integration=UserModelHealth.DEGRADED,
            queue=UserModelHealth.DEGRADED,
            snapshot_cache=UserModelHealth.DEGRADED,
            evidence_processor=UserModelHealth.DEGRADED,
            overall=UserModelHealth.DEGRADED,
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
        if self._adapter is not None:
            import asyncio
            try:
                asyncio.get_event_loop().run_until_complete(
                    self._adapter.save_behavior(pattern)
                )
            except RuntimeError:
                pass
            return
        self._behaviors[pattern.pattern_id] = pattern

    def list_behaviors(self, user_id: str, tenant_id: str) -> List[BehaviorPattern]:
        if self._adapter is not None:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                return loop.run_until_complete(
                    self._adapter.list_behaviors(user_id, tenant_id)
                )
            except RuntimeError:
                pass
        return [
            p for p in self._behaviors.values()
            if p.user_id == user_id and p.tenant_id == tenant_id
        ]

    def save_goal(self, goal: UserGoal) -> None:
        if self._adapter is not None:
            import asyncio
            try:
                asyncio.get_event_loop().run_until_complete(
                    self._adapter.save_goal(goal)
                )
            except RuntimeError:
                pass
            return
        self._goals[goal.goal_id] = goal

    def list_goals(self, user_id: str, tenant_id: str) -> List[UserGoal]:
        if self._adapter is not None:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                return loop.run_until_complete(
                    self._adapter.list_goals(user_id, tenant_id)
                )
            except RuntimeError:
                pass
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
