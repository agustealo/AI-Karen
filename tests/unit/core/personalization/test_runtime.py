"""
Unit tests for AI-Karen personalization runtime.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict

import pytest

from ai_karen_engine.core.personalization.contracts import (
    PreferenceCandidate,
    PreferenceCategory,
    PreferenceEvidenceSourceType,
    PreferenceRecord,
    PreferenceScope,
    PreferenceState,
    PreferenceStability,
    UserGoal,
)
from ai_karen_engine.core.personalization.goals.contracts import GoalStore
from ai_karen_engine.core.personalization.persistence.repository import PersonalizationRepository
from ai_karen_engine.core.personalization.runtime import UserModelRuntime


def make_runtime() -> UserModelRuntime:
    return UserModelRuntime(repository=PersonalizationRepository())


class TestUserModelRuntime:
    @pytest.mark.asyncio
    async def test_ingest_evidence_creates_preference(self):
        runtime = make_runtime()
        ev = type("E", (), {
            "evidence_id": "e1",
            "preference_key": "communication.verbosity",
            "source_type": PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT,
            "source_ref": "msg1",
            "observed_value": "concise",
            "polarity": "positive",
            "confidence": 0.9,
            "observed_at": datetime.utcnow(),
            "metadata": {"user_id": "u1", "tenant_id": "t1"},
        })()
        record = await runtime.ingest_evidence(ev)
        assert record is not None
        assert record.key == "communication.verbosity"
        assert record.state == PreferenceState.OBSERVED

    @pytest.mark.asyncio
    async def test_get_snapshot_returns_snapshot(self):
        runtime = make_runtime()
        snapshot = await runtime.get_snapshot("u1", "t1")
        assert snapshot.user_id == "u1"
        assert snapshot.tenant_id == "t1"

    @pytest.mark.asyncio
    async def test_resolve_preferences_empty_when_none(self):
        runtime = make_runtime()
        result = await runtime.resolve_preferences("u1", "t1", {"intent": "chat"})
        assert result.resolved == {}

    @pytest.mark.asyncio
    async def test_correct_preference(self):
        runtime = make_runtime()
        ev = type("E", (), {
            "evidence_id": "e1",
            "preference_key": "c.v",
            "source_type": PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT,
            "source_ref": "msg1",
            "observed_value": "old",
            "polarity": "positive",
            "confidence": 0.8,
            "observed_at": datetime.utcnow(),
            "metadata": {"user_id": "u1", "tenant_id": "t1"},
        })()
        record = await runtime.ingest_evidence(ev)
        updated = await runtime.correct_preference(record.preference_id, "new")
        assert updated is not None
        assert updated.state == PreferenceState.CONTRADICTED

    @pytest.mark.asyncio
    async def test_delete_preference(self):
        runtime = make_runtime()
        ev = type("E", (), {
            "evidence_id": "e1",
            "preference_key": "c.v",
            "source_type": PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT,
            "source_ref": "msg1",
            "observed_value": "x",
            "polarity": "positive",
            "confidence": 0.8,
            "observed_at": datetime.utcnow(),
            "metadata": {"user_id": "u1", "tenant_id": "t1"},
        })()
        record = await runtime.ingest_evidence(ev)
        assert await runtime.delete_preference(record.preference_id) is True

    @pytest.mark.asyncio
    async def test_record_goal(self):
        runtime = make_runtime()
        goal = await runtime.record_goal("u1", "t1", "ship feature")
        assert goal.description == "ship feature"
        assert goal.status == "active"

    @pytest.mark.asyncio
    async def test_health_returns_status(self):
        runtime = make_runtime()
        health = await runtime.health()
        assert health.overall in ("ready", "degraded", "unavailable")


class TestPersonalizationRepository:
    def test_save_and_get_preference(self):
        repo = PersonalizationRepository()
        rec = PreferenceRecord(
            preference_id="p1",
            user_id="u1",
            tenant_id="t1",
            key="c.v",
            value="x",
            confidence=0.8,
            stability=PreferenceStability.DURABLE,
            state=PreferenceState.STABLE,
            evidence_count=1,
            contradiction_count=0,
            first_observed_at=datetime.utcnow(),
            last_observed_at=datetime.utcnow(),
            last_confirmed_at=datetime.utcnow(),
            source_types=["explicit"],
            scope=PreferenceScope.GLOBAL,
            version=1,
            category=PreferenceCategory.COMMUNICATION,
        )
        repo.save_preference(rec)
        assert repo.get_preference("p1") is rec
        assert repo.get_preference_by_key("u1", "t1", "c.v") is rec
        assert len(repo.list_preferences("u1", "t1")) == 1

    def test_delete_preference(self):
        repo = PersonalizationRepository()
        rec = PreferenceRecord(
            preference_id="p1",
            user_id="u1",
            tenant_id="t1",
            key="c.v",
            value="x",
            confidence=0.8,
            stability=PreferenceStability.DURABLE,
            state=PreferenceState.STABLE,
            evidence_count=1,
            contradiction_count=0,
            first_observed_at=datetime.utcnow(),
            last_observed_at=datetime.utcnow(),
            last_confirmed_at=datetime.utcnow(),
            source_types=["explicit"],
            scope=PreferenceScope.GLOBAL,
            version=1,
            category=PreferenceCategory.COMMUNICATION,
        )
        repo.save_preference(rec)
        assert repo.delete_preference("p1") is True
        assert repo.get_preference("p1") is None


class TestGoalStore:
    def test_upsert_and_list(self):
        store = GoalStore()
        goal = UserGoal(
            goal_id="g1",
            user_id="u1",
            tenant_id="t1",
            description="ship",
            scope="global",
            status="active",
            confidence=0.8,
            evidence=[],
            started_at=datetime.utcnow(),
            last_observed_at=datetime.utcnow(),
        )
        store.upsert(goal)
        assert store.get("g1") is goal
        assert len(store.list_active("u1", "t1")) == 1


__all__ = ["TestUserModelRuntime", "TestPersonalizationRepository", "TestGoalStore"]
