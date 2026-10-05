"""Unit tests for the derived personalization runtime."""

from __future__ import annotations

from datetime import datetime
import pytest

from ai_karen_engine.core.personalization.behavior.contracts import BehaviorObservation
from ai_karen_engine.core.personalization.contracts import (
    BehaviorPattern,
    PreferenceCategory,
    PreferenceRecord,
    PreferenceScope,
    PreferenceStability,
    PreferenceState,
    UserGoal,
    UserGoalStatus,
    UserModelHealth,
    UserModelHealthStatus,
)
from ai_karen_engine.core.personalization.persistence.repository import (
    PersonalizationRepository,
)
from ai_karen_engine.core.personalization.runtime import UserModelRuntime


class _Repository(PersonalizationRepository):
    def __init__(self) -> None:
        self.preferences: list[PreferenceRecord] = []
        self.goals: list[UserGoal] = []
        self.behaviors: list[BehaviorPattern] = []

    async def health_check(self) -> UserModelHealthStatus:
        return UserModelHealthStatus(
            repository=UserModelHealth.READY,
            memory_integration=UserModelHealth.READY,
            queue=UserModelHealth.READY,
            snapshot_cache=UserModelHealth.READY,
            evidence_processor=UserModelHealth.READY,
            overall=UserModelHealth.READY,
        )

    async def list_preferences(self, user_id: str, tenant_id: str) -> list[PreferenceRecord]:
        return [
            item
            for item in self.preferences
            if item.user_id == user_id and item.tenant_id == tenant_id
        ]

    async def list_goals(self, user_id: str, tenant_id: str) -> list[UserGoal]:
        return [
            item
            for item in self.goals
            if item.user_id == user_id and item.tenant_id == tenant_id
        ]

    async def save_behavior(self, pattern: BehaviorPattern) -> None:
        existing = next(
            (
                item
                for item in self.behaviors
                if item.user_id == pattern.user_id
                and item.tenant_id == pattern.tenant_id
                and item.pattern_type == pattern.pattern_type
                and item.context_signature == pattern.context_signature
            ),
            None,
        )
        if existing is None:
            self.behaviors.append(pattern)
        else:
            self.behaviors[self.behaviors.index(existing)] = pattern

    async def list_behaviors(self, user_id: str, tenant_id: str) -> list[BehaviorPattern]:
        return [
            item
            for item in self.behaviors
            if item.user_id == user_id and item.tenant_id == tenant_id
        ]


def _preference() -> PreferenceRecord:
    now = datetime.utcnow()
    return PreferenceRecord(
        preference_id="p1",
        user_id="u1",
        tenant_id="t1",
        key="communication.verbosity",
        value="concise",
        confidence=0.95,
        stability=PreferenceStability.LONG_TERM,
        state=PreferenceState.STABLE,
        evidence_count=1,
        contradiction_count=0,
        first_observed_at=now,
        last_observed_at=now,
        last_confirmed_at=now,
        source_types=["chat_user"],
        scope=PreferenceScope.GLOBAL,
        version=1,
        category=PreferenceCategory.COMMUNICATION,
    )


def _goal() -> UserGoal:
    now = datetime.utcnow()
    return UserGoal(
        goal_id="g1",
        user_id="u1",
        tenant_id="t1",
        description="ship the release",
        scope=PreferenceScope.GLOBAL,
        status=UserGoalStatus.ACTIVE,
        confidence=0.9,
        evidence=["conversation-1"],
        started_at=now,
        last_observed_at=now,
    )


def _behavior_observation(observation_id: str) -> BehaviorObservation:
    return BehaviorObservation(
        observation_id=observation_id,
        pattern_id="",
        user_id="u1",
        tenant_id="t1",
        context_signature="workflow=audit",
        action="accept_suggestion",
        outcome="accepted",
        observed_at=datetime.utcnow(),
        metadata={"confidence": 0.8},
    )


def test_runtime_requires_explicit_repository() -> None:
    with pytest.raises(ValueError, match="explicit repository"):
        UserModelRuntime(repository=None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_snapshot_derives_preferences_and_goals_from_repository() -> None:
    repository = _Repository()
    repository.preferences.append(_preference())
    repository.goals.append(_goal())
    runtime = UserModelRuntime(repository=repository)

    snapshot = await runtime.get_snapshot("u1", "t1")

    assert [item.preference_id for item in snapshot.stable_preferences] == ["p1"]
    assert [item.goal_id for item in snapshot.active_goals] == ["g1"]


@pytest.mark.asyncio
async def test_current_state_is_explicitly_ephemeral() -> None:
    repository = _Repository()
    first = UserModelRuntime(repository=repository)
    await first.update_current_state(
        "u1",
        "t1",
        {"current_project": "Karen", "current_objective": "audit"},
    )

    first_snapshot = await first.get_snapshot("u1", "t1")
    second = UserModelRuntime(repository=repository)
    second_snapshot = await second.get_snapshot("u1", "t1")

    assert first_snapshot.current_state.current_project == "Karen"
    assert second_snapshot.current_state.current_project is None


@pytest.mark.asyncio
async def test_behavior_learning_survives_runtime_reconstruction_via_repository() -> None:
    repository = _Repository()
    first = UserModelRuntime(repository=repository)
    second = UserModelRuntime(repository=repository)

    first_pattern = await first.ingest_behavior_observation(
        _behavior_observation("obs-1")
    )
    second_pattern = await second.ingest_behavior_observation(
        _behavior_observation("obs-2")
    )

    assert first_pattern.observation_count == 1
    assert second_pattern.observation_count == 2
    assert second_pattern.pattern_type == "accept_suggestion"


@pytest.mark.asyncio
async def test_health_is_repository_backed() -> None:
    runtime = UserModelRuntime(repository=_Repository())

    health = await runtime.health()

    assert health.overall is UserModelHealth.READY


__all__ = ["_Repository"]
