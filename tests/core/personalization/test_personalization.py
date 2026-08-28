"""
Integration and adversarial tests for AI-Karen personalization boundaries.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

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
            metadata={"user_id": "u1", "tenant_id": "t1", "session_id": "s1"},
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

    @pytest.mark.asyncio
    async def test_current_state_hydrates_across_runtime_instances(self):
        repository = PersonalizationRepository()
        first_runtime = UserModelRuntime(repository=repository)
        await first_runtime.update_current_state(
            "u1",
            "t1",
            {"current_project": "Karen", "current_objective": "audit"},
        )

        second_runtime = UserModelRuntime(repository=repository)
        snapshot = await second_runtime.get_snapshot("u1", "t1")

        assert snapshot.current_state.current_project == "Karen"
        assert snapshot.current_state.current_objective == "audit"


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
        await runtime.ingest_evidence(ev1)
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
        assert rec2 is not None
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

    @pytest.mark.asyncio
    async def test_scope_precedence_is_deterministic(self):
        runtime = UserModelRuntime(repository=PersonalizationRepository())
        evidence = PreferenceEvidence(
            evidence_id="scope-e1",
            preference_key="communication.verbosity",
            source_type=PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT,
            source_ref="scope-msg",
            observed_value="concise",
            polarity="positive",
            confidence=0.9,
            observed_at=datetime.utcnow(),
            metadata={
                "user_id": "u1",
                "tenant_id": "t1",
                "domain": "architecture",
                "task_type": "audit",
                "project_id": "karen",
                "conversation_id": "c1",
                "session_id": "s1",
            },
        )
        record = await runtime.ingest_evidence(evidence)
        assert record is not None
        assert record.scope == PreferenceScope.SESSION


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

    @pytest.mark.asyncio
    async def test_identical_evidence_cannot_dedupe_across_tenants(self):
        runtime = UserModelRuntime(repository=PersonalizationRepository())
        common = {
            "preference_key": "communication.verbosity",
            "source_type": PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT,
            "source_ref": "same-source-ref",
            "observed_value": "concise",
            "polarity": "positive",
            "confidence": 0.9,
            "observed_at": datetime.utcnow(),
        }
        tenant_a = PreferenceEvidence(
            evidence_id="tenant-a",
            metadata={"user_id": "u1", "tenant_id": "tA"},
            **common,
        )
        tenant_b = PreferenceEvidence(
            evidence_id="tenant-b",
            metadata={"user_id": "u1", "tenant_id": "tB"},
            **common,
        )

        rec_a = await runtime.ingest_evidence(tenant_a)
        rec_b = await runtime.ingest_evidence(tenant_b)

        assert rec_a is not None
        assert rec_b is not None
        assert rec_a.preference_id != rec_b.preference_id
        assert runtime.evidence_store.count(
            "communication.verbosity", user_id="u1", tenant_id="tA"
        ) == 1
        assert runtime.evidence_store.count(
            "communication.verbosity", user_id="u1", tenant_id="tB"
        ) == 1

    def test_evidence_store_requires_subject_scope(self):
        store = PreferenceEvidenceStore()
        evidence = PreferenceEvidence(
            evidence_id="unscoped",
            preference_key="communication.verbosity",
            source_type=PreferenceEvidenceSourceType.SYSTEM_INFERENCE,
            source_ref="model-output",
            observed_value="concise",
            polarity="positive",
            confidence=0.5,
            observed_at=datetime.utcnow(),
            metadata={},
        )
        with pytest.raises(ValueError, match="tenant_id and user_id"):
            store.add(evidence)


class TestBehaviorAccumulation:
    @staticmethod
    def _successful_outcome():
        return SimpleNamespace(
            user_id="u1",
            tenant_id="t1",
            metadata={"workflow": "audit"},
            execution_outcome=SimpleNamespace(
                tool_success=True,
                fallback_count=0,
                response_completed=True,
            ),
        )

    @pytest.mark.asyncio
    async def test_repeated_behavior_accumulates_across_runtime_instances(self):
        repository = PersonalizationRepository()
        first_runtime = UserModelRuntime(repository=repository)
        second_runtime = UserModelRuntime(repository=repository)

        first = await first_runtime.ingest_outcome(self._successful_outcome())
        second = await second_runtime.ingest_outcome(self._successful_outcome())

        assert first == []
        assert len(second) == 1
        assert second[0].observation_count == 2
        assert second[0].user_id == "u1"
        assert second[0].tenant_id == "t1"

        exposed = await second_runtime.get_behavior_patterns("u1", "t1")
        assert len(exposed) == 1
        assert exposed[0].observation_count == 2


class TestGoalPersistence:
    @pytest.mark.asyncio
    async def test_goal_survives_runtime_reconstruction(self):
        repository = PersonalizationRepository()
        first_runtime = UserModelRuntime(repository=repository)
        created = await first_runtime.record_goal(
            "u1",
            "t1",
            "Finish the personalization authority audit",
        )

        second_runtime = UserModelRuntime(repository=repository)
        snapshot = await second_runtime.get_snapshot("u1", "t1")

        assert [goal.goal_id for goal in snapshot.active_goals] == [created.goal_id]


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
    "TestBehaviorAccumulation",
    "TestGoalPersistence",
    "TestEvaluationCorpus",
]
