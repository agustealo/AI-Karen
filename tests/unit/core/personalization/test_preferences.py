"""
Unit tests for AI-Karen personalization preferences.
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
from ai_karen_engine.core.personalization.preferences.catalog import PreferenceCatalog
from ai_karen_engine.core.personalization.preferences.drift import DriftDetector
from ai_karen_engine.core.personalization.preferences.drift import DriftState
from ai_karen_engine.core.personalization.preferences.evidence import PreferenceEvidenceStore
from ai_karen_engine.core.personalization.preferences.lifecycle import PreferenceLifecycle
from ai_karen_engine.core.personalization.preferences.resolver import PreferenceResolver


def make_record(
    state: PreferenceState = PreferenceState.OBSERVED,
    stability: PreferenceStability = PreferenceStability.SESSION,
    confidence: float = 0.5,
    scope: PreferenceScope = PreferenceScope.SESSION,
    category: PreferenceCategory = PreferenceCategory.COMMUNICATION,
) -> PreferenceRecord:
    return PreferenceRecord(
        preference_id="p1",
        user_id="u1",
        tenant_id="t1",
        key="communication.verbosity",
        value="concise",
        confidence=confidence,
        stability=stability,
        state=state,
        evidence_count=1,
        contradiction_count=0,
        first_observed_at=datetime.utcnow(),
        last_observed_at=datetime.utcnow(),
        last_confirmed_at=datetime.utcnow(),
        source_types=["explicit"],
        scope=scope,
        version=1,
        category=category,
    )


class TestPreferenceLifecycle:
    def test_promote_tentative_to_established(self):
        rec = make_record(state=PreferenceState.TENTATIVE, confidence=0.82)
        result = PreferenceLifecycle.promote(rec, 0.82)
        assert result.state == PreferenceState.ESTABLISHED

    def test_promote_established_to_stable(self):
        rec = make_record(state=PreferenceState.ESTABLISHED, confidence=0.92)
        result = PreferenceLifecycle.promote(rec, 0.92)
        assert result.state == PreferenceState.STABLE

    def test_decay_session_preference(self):
        rec = make_record(stability=PreferenceStability.SESSION, confidence=0.5)
        result = PreferenceLifecycle.decay(rec, decay_factor=0.3)
        assert result.state == PreferenceState.DECAYING

    def test_contradiction_increments(self):
        rec = make_record()
        rec, contra = PreferenceLifecycle.contradict(rec, "detailed", 0.9)
        assert rec.state == PreferenceState.CONTRADICTED
        assert rec.contradiction_count == 1
        assert rec.version == 2

    def test_retire(self):
        rec = make_record()
        result = PreferenceLifecycle.retire(rec)
        assert result.state == PreferenceState.RETIRED
        assert result.confidence == 0.0


class TestPreferenceEvidenceStore:
    def test_add_and_count(self):
        store = PreferenceEvidenceStore()
        ev = PreferenceEvidence(
            evidence_id="e1",
            preference_key="c.v",
            source_type=PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT,
            source_ref="msg1",
            observed_value="concise",
            polarity="positive",
            confidence=0.9,
            observed_at=datetime.utcnow(),
        )
        assert store.add(ev) is True
        assert store.add(ev) is False
        assert store.count("c.v") == 1

    def test_compute_confidence(self):
        store = PreferenceEvidenceStore()
        now = datetime.utcnow()
        store.add(PreferenceEvidence(
            evidence_id="e1",
            preference_key="c.v",
            source_type=PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT,
            source_ref="msg1",
            observed_value="concise",
            polarity="positive",
            confidence=0.9,
            observed_at=now,
        ))
        conf = store.compute_confidence("c.v")
        assert conf > 0.0


class TestPreferenceResolver:
    def test_global_preference_applies(self):
        resolver = PreferenceResolver()
        snapshot = type("S", (), {
            "user_id": "u1",
            "tenant_id": "t1",
            "stable_preferences": [make_record(scope=PreferenceScope.GLOBAL)],
            "tentative_preferences": [],
        })()
        result = resolver.resolve(snapshot, {"intent": "chat"})
        assert "communication.verbosity" in result.resolved

    def test_temporary_preference_does_not_leak(self):
        resolver = PreferenceResolver()
        snapshot = type("S", (), {
            "user_id": "u1",
            "tenant_id": "t1",
            "stable_preferences": [],
            "tentative_preferences": [
                make_record(scope=PreferenceScope.CONVERSATION, state=PreferenceState.TENTATIVE)
            ],
        })()
        result = resolver.resolve(snapshot, {"intent": "chat"}, requested_scope=PreferenceScope.GLOBAL)
        assert "communication.verbosity" not in result.resolved


class TestDriftDetector:
    def test_stable_when_fresh(self):
        detector = DriftDetector()
        rec = make_record(state=PreferenceState.STABLE, confidence=0.95)
        detector.evaluate(rec)
        detector.evaluate(rec)
        assert detector.evaluate(rec) == DriftState.STABLE.value

    def test_watch_after_contradictions(self):
        detector = DriftDetector()
        rec = make_record(state=PreferenceState.CONTRADICTED, confidence=0.3)
        rec.contradiction_count = 3
        rec.evidence_count = 4
        detector.evaluate(rec)
        detector.evaluate(rec)
        state = detector.evaluate(rec)
        assert state in (DriftState.WATCH.value, DriftState.DRIFTING.value)


class TestPreferenceCatalog:
    def test_evidence_weights_explicit_highest(self):
        w1 = PreferenceCatalog.get_evidence_weight(PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT)
        w2 = PreferenceCatalog.get_evidence_weight(PreferenceEvidenceSourceType.SYSTEM_INFERENCE)
        assert w1 > w2

    def test_promotion_thresholds_increase(self):
        t1 = PreferenceCatalog.get_promotion_threshold("session")
        t2 = PreferenceCatalog.get_promotion_threshold("durable")
        assert t2["min_evidence"] >= t1["min_evidence"]


__all__ = [
    "TestPreferenceLifecycle",
    "TestPreferenceEvidenceStore",
    "TestPreferenceResolver",
    "TestDriftDetector",
    "TestPreferenceCatalog",
]
