"""
Unit tests for AI-Karen personalization contracts.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List

import pytest

from ai_karen_engine.core.personalization.contracts import (
    BehaviorPattern,
    CurrentUserState,
    PreferenceCategory,
    PreferenceContradiction,
    PreferenceEvidence,
    PreferenceEvidenceSourceType,
    PreferenceRecord,
    PreferenceScope,
    PreferenceState,
    PreferenceStability,
    ResolvedPreferences,
    UserGoal,
    UserGoalStatus,
    UserModelHealth,
    UserStateSnapshot,
    make_evidence_id,
    make_goal_id,
    make_pattern_id,
    make_preference_id,
)


class TestPreferenceRecord:
    def test_default_confidence_clamped(self):
        rec = PreferenceRecord(
            preference_id=make_preference_id(),
            user_id="u1",
            tenant_id="t1",
            key="communication.verbosity",
            value="concise",
            confidence=1.5,
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
        assert rec.confidence == 1.0

    def test_negative_evidence_count_clamped(self):
        rec = PreferenceRecord(
            preference_id=make_preference_id(),
            user_id="u1",
            tenant_id="t1",
            key="tool.editor",
            value="vim",
            confidence=0.8,
            stability=PreferenceStability.LONG_TERM,
            state=PreferenceState.ESTABLISHED,
            evidence_count=-5,
            contradiction_count=0,
            first_observed_at=datetime.utcnow(),
            last_observed_at=datetime.utcnow(),
            last_confirmed_at=datetime.utcnow(),
            source_types=[],
            scope=PreferenceScope.GLOBAL,
            version=0,
            category=PreferenceCategory.TOOL,
        )
        assert rec.evidence_count == 0
        assert rec.version == 1


class TestCurrentUserState:
    def test_fast_state_expiration(self):
        state = CurrentUserState(
            user_id="u1",
            tenant_id="t1",
            current_project="KAREN",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        assert not state.expires_at or state.expires_at > datetime.utcnow()


class TestUserStateSnapshot:
    def test_snapshot_contains_preferences(self):
        prefs = [
            PreferenceRecord(
                preference_id=make_preference_id(),
                user_id="u1",
                tenant_id="t1",
                key="c.v",
                value="x",
                confidence=0.9,
                stability=PreferenceStability.DURABLE,
                state=PreferenceState.STABLE,
                evidence_count=10,
                contradiction_count=0,
                first_observed_at=datetime.utcnow(),
                last_observed_at=datetime.utcnow(),
                last_confirmed_at=datetime.utcnow(),
                source_types=["explicit"],
                scope=PreferenceScope.GLOBAL,
                version=1,
                category=PreferenceCategory.COMMUNICATION,
            )
        ]
        snapshot = UserStateSnapshot(
            user_id="u1",
            tenant_id="t1",
            current_state=CurrentUserState(user_id="u1", tenant_id="t1"),
            stable_preferences=prefs,
            tentative_preferences=[],
            behavior_patterns=[],
            active_goals=[],
            confidence_summary={},
            generated_at=datetime.utcnow(),
        )
        assert len(snapshot.stable_preferences) == 1


class TestPreferenceEvidence:
    def test_confidence_clamped(self):
        ev = PreferenceEvidence(
            evidence_id=make_evidence_id(),
            preference_key="c.v",
            source_type=PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT,
            source_ref="msg1",
            observed_value="concise",
            polarity="positive",
            confidence=2.0,
            observed_at=datetime.utcnow(),
        )
        assert ev.confidence == 1.0


class TestUserGoal:
    def test_goal_confidence_clamped(self):
        goal = UserGoal(
            goal_id=make_goal_id(),
            user_id="u1",
            tenant_id="t1",
            description="ship feature",
            scope="global",
            status=UserGoalStatus.ACTIVE,
            confidence=1.5,
            evidence=[],
            started_at=datetime.utcnow(),
            last_observed_at=datetime.utcnow(),
        )
        assert goal.confidence == 1.0


__all__ = [
    "TestPreferenceRecord",
    "TestCurrentUserState",
    "TestUserStateSnapshot",
    "TestPreferenceEvidence",
    "TestUserGoal",
]
