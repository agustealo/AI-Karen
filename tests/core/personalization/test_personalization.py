"""
Integration tests for AI-Karen personalization key scenarios.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from ai_karen_engine.core.personalization.contracts import (
    PreferenceCategory,
    PreferenceEvidence,
    PreferenceEvidenceSourceType,
    PreferenceRecord,
    PreferenceScope,
    PreferenceState,
    PreferenceStability,
)
from ai_karen_engine.core.personalization.evaluation.corpus import EvaluationCorpus
from ai_karen_engine.core.personalization.persistence.repository import PersonalizationRepository
from ai_karen_engine.core.personalization.preferences.evidence import PreferenceEvidenceStore
from ai_karen_engine.core.personalization.preferences.lifecycle import PreferenceLifecycle
from ai_karen_engine.core.personalization.runtime import UserModelRuntime


class TestFastSlowState:
    @pytest.mark.asyncio
    async def test_session_preference_does_not_become_global(self):
        runtime = UserModelRuntime(repository=PersonalizationRepository())
        ev = PreferenceEvidence(
            evidence_id="e1",
            preference_key="interaction.verbosity",
            source_type=PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT,
            source_ref="msg1",
            observed_value="terse",
            polarity="positive",
            confidence=0.8,
            observed_at=datetime.utcnow(),
            metadata={"user_id": "u1", "tenant_id": "t1"},
        )
        record = await runtime.ingest_evidence(ev)
        assert record is not None
        assert record.scope == PreferenceScope.SESSION
        snapshot = await runtime.get_snapshot("u1", "t1")
        assert all(p.scope != PreferenceScope.GLOBAL for p in snapshot.tentative_preferences)

    @pytest.mark.asyncio
    async def test_durable_preference_promoted(self):
        runtime = UserModelRuntime(repository=PersonalizationRepository())
        for i in range(5):
            ev = PreferenceEvidence(
                evidence_id=f"e{i}",
                preference_key="model.locality",
                source_type=PreferenceEvidenceSourceType.TOOL_SELECTION,
                source_ref=f"msg{i}",
                observed_value="local",
                polarity="positive",
                confidence=0.8,
                observed_at=datetime.utcnow() - timedelta(days=i),
                metadata={"user_id": "u1", "tenant_id": "t1"},
            )
            await runtime.ingest_evidence(ev)
        prefs = runtime.repository.list_preferences("u1", "t1")
        assert len(prefs) == 1
        assert prefs[0].evidence_count >= 1


class TestContradictionHandling:
    @pytest.mark.asyncio
    async def test_contradiction_records_version(self):
        runtime = UserModelRuntime(repository=PersonalizationRepository())
        ev1 = PreferenceEvidence(
            evidence_id="e1",
            preference_key="communication.verbosity",
            source_type=PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT,
            source_ref="msg1",
            observed_value="concise",
            polarity="positive",
            confidence=0.9,
            observed_at=datetime.utcnow(),
            metadata={"user_id": "u1", "tenant_id": "t1"},
        )
        rec = await runtime.ingest_evidence(ev1)
        ev2 = PreferenceEvidence(
            evidence_id="e2",
            preference_key="communication.verbosity",
            source_type=PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT,
            source_ref="msg2",
            observed_value="detailed",
            polarity="negative",
            confidence=0.9,
            observed_at=datetime.utcnow(),
            metadata={"user_id": "u1", "tenant_id": "t1"},
        )
        rec2 = await runtime.ingest_evidence(ev2)
        assert rec2.contradiction_count >= 1
        assert rec2.version >= 2


class TestScopeResolution:
    @pytest.mark.asyncio
    async def test_global_and_domain_coexist(self):
        runtime = UserModelRuntime(repository=PersonalizationRepository())
        ev_global = PreferenceEvidence(
            evidence_id="e1",
            preference_key="communication.verbosity",
            source_type=PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT,
            source_ref="msg1",
            observed_value="concise",
            polarity="positive",
            confidence=0.9,
            observed_at=datetime.utcnow(),
            metadata={"user_id": "u1", "tenant_id": "t1"},
        )
        await runtime.ingest_evidence(ev_global)
        ev_domain = PreferenceEvidence(
            evidence_id="e2",
            preference_key="communication.verbosity",
            source_type=PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT,
            source_ref="msg2",
            observed_value="detailed",
            polarity="positive",
            confidence=0.9,
            observed_at=datetime.utcnow(),
            metadata={"user_id": "u1", "tenant_id": "t1", "domain": "architecture_audit"},
        )
        rec = await runtime.ingest_evidence(ev_domain)
        assert rec is not None
        snapshot = await runtime.get_snapshot("u1", "t1")
        keys = [p.key for p in snapshot.stable_preferences] + [p.key for p in snapshot.tentative_preferences]
        assert "communication.verbosity" in keys


class TestCrossTenantIsolation:
    def test_preferences_scoped_by_tenant(self):
        repo = PersonalizationRepository()
        rec_a = PreferenceRecord(
            preference_id="p_a",
            user_id="u1",
            tenant_id="tA",
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
        repo.save_preference(rec_a)
        assert repo.get_preference_by_key("u1", "tB", "c.v") is None
        assert repo.get_preference_by_key("u1", "tA", "c.v") is rec_a


class TestEvaluationCorpus:
    def test_all_cases_present(self):
        cases = EvaluationCorpus.all_cases()
        names = [c["name"] for c in cases]
        assert "explicit_preference" in names
        assert "temporary_preference" in names
        assert "contradictory_preference" in names
        assert "repeated_behavior" in names
        assert "domain_scoped_preference" in names
        assert "single_weak_behavior" in names
        assert "preference_reversal" in names
        assert "stale_preference" in names

    def test_explicit_preference_expected_stable(self):
        case = EvaluationCorpus.explicit_preference_case()
        assert case["expected"]["state"] == PreferenceState.STABLE


__all__ = [
    "TestFastSlowState",
    "TestContradictionHandling",
    "TestScopeResolution",
    "TestCrossTenantIsolation",
    "TestEvaluationCorpus",
]
