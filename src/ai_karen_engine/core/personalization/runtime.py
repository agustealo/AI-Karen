"""Derived personalization runtime.

Personalization consumes canonical Memory user-state projections and durable
behavior evidence. It does not own user facts, preferences, goals, or a second
persistence authority.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict

from .behavior.aggregator import BehaviorAggregator
from .behavior.contracts import BehaviorObservation
from .contracts import (
    BehaviorCandidate,
    BehaviorPattern,
    CurrentUserState,
    PreferenceStability,
    ResolvedPreferences,
    UserModelHealth,
    UserModelHealthStatus,
    UserStateSnapshot,
    make_pattern_id,
)
from .persistence.repository import PersonalizationRepository
from .preferences.resolver import PreferenceResolver
from .snapshot import SnapshotBuilder

logger = logging.getLogger(__name__)

try:
    from ai_karen_engine.monitoring.personalization_metrics import get_personalization_metrics

    _personalization_metrics = get_personalization_metrics()
except Exception:
    _personalization_metrics = None


class UserModelRuntime:
    """Read/learning runtime backed by an explicit repository port."""

    _BEHAVIOR_PROMOTION_THRESHOLD = 2

    def __init__(self, repository: PersonalizationRepository) -> None:
        if repository is None:
            raise ValueError("UserModelRuntime requires an explicit repository")
        self.repository = repository
        self.behavior_aggregator = BehaviorAggregator()
        self.resolver = PreferenceResolver()
        self._current_states: dict[str, CurrentUserState] = {}

    def _state_key(self, user_id: str, tenant_id: str) -> str:
        return f"{tenant_id}:{user_id}"

    def _get_current_state(self, user_id: str, tenant_id: str) -> CurrentUserState:
        key = self._state_key(user_id, tenant_id)
        return self._current_states.get(
            key,
            CurrentUserState(user_id=user_id, tenant_id=tenant_id),
        )

    async def get_snapshot(self, user_id: str, tenant_id: str) -> UserStateSnapshot:
        start = time.perf_counter()
        state = self._get_current_state(user_id, tenant_id)
        preferences = await self.repository.list_preferences(user_id, tenant_id)
        behavior_records = await self.repository.list_behaviors(user_id, tenant_id)
        behaviors = [
            pattern
            for pattern in behavior_records
            if pattern.observation_count >= self._BEHAVIOR_PROMOTION_THRESHOLD
        ]
        goals = await self.repository.list_goals(user_id, tenant_id)
        snapshot = SnapshotBuilder(user_id, tenant_id).build(
            state,
            preferences,
            behaviors,
            goals,
        )
        duration = time.perf_counter() - start
        if _personalization_metrics is not None:
            try:
                _personalization_metrics.record_snapshot(
                    status="success",
                    duration_seconds=duration,
                )
            except Exception:
                logger.debug(
                    "Unable to record personalization snapshot metric",
                    exc_info=True,
                )
        return snapshot

    async def ingest_behavior_observation(
        self,
        observation: BehaviorObservation,
    ) -> BehaviorPattern:
        """Accumulate an explicit user-behavior observation durably."""

        candidate = self.behavior_aggregator.observe(observation)
        return await self._accumulate_behavior(candidate)

    async def _accumulate_behavior(self, candidate: BehaviorCandidate) -> BehaviorPattern:
        return await self.repository.accumulate_behavior(candidate)

    async def update_current_state(
        self,
        user_id: str,
        tenant_id: str,
        updates: Dict[str, Any],
    ) -> None:
        """Update explicitly ephemeral current state only."""
        state = self._get_current_state(user_id, tenant_id)
        for key, value in updates.items():
            if hasattr(state, key):
                setattr(state, key, value)
        self._current_states[self._state_key(user_id, tenant_id)] = state

    async def resolve_preferences(
        self,
        user_id: str,
        tenant_id: str,
        task_context: Dict[str, Any],
        scope: Any = None,
    ) -> ResolvedPreferences:
        snapshot = await self.get_snapshot(user_id, tenant_id)
        return self.resolver.resolve(snapshot, task_context, scope)

    async def get_behavior_patterns(
        self,
        user_id: str,
        tenant_id: str,
    ) -> list[BehaviorPattern]:
        patterns = await self.repository.list_behaviors(user_id, tenant_id)
        return [
            pattern
            for pattern in patterns
            if pattern.observation_count >= self._BEHAVIOR_PROMOTION_THRESHOLD
        ]

    async def health(self) -> UserModelHealthStatus:
        repo_health = await self.repository.health_check()
        return UserModelHealthStatus(
            repository=repo_health.repository,
            memory_integration=repo_health.memory_integration,
            queue=repo_health.queue,
            snapshot_cache=repo_health.snapshot_cache,
            evidence_processor=UserModelHealth.READY,
            overall=repo_health.overall,
        )


__all__ = ["UserModelRuntime"]
