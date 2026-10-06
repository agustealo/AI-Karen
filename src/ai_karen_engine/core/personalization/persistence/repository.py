"""Repository contract for derived personalization state.

Core defines the port only. Platform owns persistence. User facts, preferences,
goals, commitments, and open loops remain canonical Memory/NeuroVault state;
implementations may only derive those views and persist non-authoritative
behavior-learning evidence.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..contracts import (
    BehaviorCandidate,
    BehaviorPattern,
    PreferenceRecord,
    UserGoal,
    UserModelHealthStatus,
)


class PersonalizationRepository(ABC):
    """Persistence/read-model port for personalization consumers."""

    @abstractmethod
    async def health_check(self) -> UserModelHealthStatus:
        """Return evidence-backed repository health."""

    @abstractmethod
    async def list_preferences(
        self,
        user_id: str,
        tenant_id: str,
    ) -> list[PreferenceRecord]:
        """Read current preferences derived from canonical memory."""

    @abstractmethod
    async def list_goals(
        self,
        user_id: str,
        tenant_id: str,
    ) -> list[UserGoal]:
        """Read current goals derived from canonical memory."""

    @abstractmethod
    async def accumulate_behavior(
        self,
        candidate: BehaviorCandidate,
    ) -> BehaviorPattern:
        """Atomically record one deduplicated behavior observation."""

    @abstractmethod
    async def save_behavior(self, pattern: BehaviorPattern) -> None:
        """Persist recurring behavior evidence."""

    @abstractmethod
    async def list_behaviors(
        self,
        user_id: str,
        tenant_id: str,
    ) -> list[BehaviorPattern]:
        """Read recurring behavior evidence."""


__all__ = ["PersonalizationRepository"]
