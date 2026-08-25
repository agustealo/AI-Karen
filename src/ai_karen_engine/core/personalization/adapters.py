"""
Personalization Adapters for AI-Karen

Adapters bridge core personalization to platform persistence implementations.

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ai_karen_engine.core.personalization.contracts import (
    BehaviorPattern,
    PreferenceRecord,
    PreferenceState,
    UserGoal,
    UserModelHealth,
    UserModelHealthStatus,
)


class PersonalizationRepositoryAdapter:
    """Adapter that wraps platform personalization repository."""

    def __init__(self, platform_repository):
        self._repository = platform_repository

    async def health_check(self) -> UserModelHealthStatus:
        """Evidence-backed health check."""
        return await self._repository.health_check()

    async def save_preference(self, record: PreferenceRecord) -> None:
        """Save a preference."""
        await self._repository.save_preference(record)

    async def get_preference(self, preference_id: str) -> Optional[PreferenceRecord]:
        """Get a preference by ID."""
        return await self._repository.get_preference(preference_id)

    async def get_preference_by_key(self, user_id: str, tenant_id: str, key: str) -> Optional[PreferenceRecord]:
        """Get a preference by key."""
        return await self._repository.get_preference_by_key(user_id, tenant_id, key)

    async def list_preferences(self, user_id: str, tenant_id: str) -> List[PreferenceRecord]:
        """List preferences."""
        return await self._repository.list_preferences(user_id, tenant_id)

    async def delete_preference(self, preference_id: str) -> bool:
        """Delete a preference."""
        return await self._repository.delete_preference(preference_id)

    async def save_behavior(self, pattern: BehaviorPattern) -> None:
        """Save a behavior pattern."""
        await self._repository.save_behavior(pattern)

    async def list_behaviors(self, user_id: str, tenant_id: str) -> List[BehaviorPattern]:
        """List behaviors."""
        return await self._repository.list_behaviors(user_id, tenant_id)

    async def save_goal(self, goal: UserGoal) -> None:
        """Save a goal."""
        await self._repository.save_goal(goal)

    async def list_goals(self, user_id: str, tenant_id: str) -> List[UserGoal]:
        """List goals."""
        return await self._repository.list_goals(user_id, tenant_id)
