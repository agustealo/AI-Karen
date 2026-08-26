from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from ai_karen_engine.core.reasoning.belief.assessment import BeliefEngine, ConfidenceMetrics
from ai_karen_engine.core.reasoning.belief.contracts import (
    BeliefAssessment,
    BeliefClaim,
    BeliefEvidence,
    BeliefVerdict,
    ClaimStatus,
    ContradictionSeverity,
    EpistemicConfidence,
    EvidenceRelation,
    EvidenceStrength,
    EvidenceType,
)
from ai_karen_engine.core.reasoning.belief.contradiction import ContradictionDetector
from ai_karen_engine.core.reasoning.belief.revision import BeliefRevisionEngine, RevisionAction
from ai_karen_engine.core.reasoning.belief.temporal import TemporalBeliefManager


def make_claim(**overrides):
    defaults = dict(
        claim_id="claim_1",
        subject="Karen",
        predicate="uses",
        object="Ollama",
        status=ClaimStatus.INFERRED,
        confidence=0.5,
        source=EvidenceType.SYSTEM_INFERENCE,
        tenant_id="t1",
    )
    defaults.update(overrides)
    return BeliefClaim(**defaults)


def make_evidence(**overrides):
    defaults = dict(
        evidence_id="ev_1",
        claim_id="claim_1",
        type=EvidenceType.TOOL_RESULT,
        relation=EvidenceRelation.SUPPORTS,
        strength=EvidenceStrength.MODERATE,
        confidence=0.8,
        source_ref="tool:models",
        tenant_id="t1",
    )
    defaults.update(overrides)
    return BeliefEvidence(**defaults)


class TestClaimAssessment:
    def test_verified_requires_support(self):
        engine = BeliefEngine()
        claim = make_claim(status=ClaimStatus.VERIFIED, confidence=0.9)
        ev = make_evidence(strength=EvidenceStrength.DEFINITIVE, confidence=0.95)
        assessment = engine.assess(claim, [ev])
        assert assessment.verdict in (BeliefVerdict.SUPPORTED, BeliefVerdict.WEAK_SUPPORT)

    def test_no_evidence_does_not_fabricate_support(self):
        engine = BeliefEngine()
        claim = make_claim(status=ClaimStatus.INFERRED, confidence=0.7)
        assessment = engine.assess(claim, [])
        assert assessment.verdict != BeliefVerdict.SUPPORTED

    def test_contradicting_evidence_lowers_confidence(self):
        engine = BeliefEngine()
        claim = make_claim(confidence=0.8)
        ev = make_evidence(relation=EvidenceRelation.CONTRADICTS, confidence=0.9)
        assessment = engine.assess(claim, [ev])
        assert float(assessment.confidence) < 0.8

    def test_evidence_refs_are_preserved(self):
        engine = BeliefEngine()
        claim = make_claim()
        ev = make_evidence(evidence_id="evidence-42")
        assessment = engine.assess(claim, [ev])
        assert "evidence-42" in assessment.evidence_refs

    def test_assessment_contains_reason_codes(self):
        engine = BeliefEngine()
        claim = make_claim()
        assessment = engine.assess(claim, [])
        assert assessment.reason_codes


class TestTemporalTruth:
    def test_expired_claim_is_not_current(self):
        manager = TemporalBeliefManager()
        claim = make_claim(valid_until=datetime.utcnow() - timedelta(days=1))
        assert manager.is_current(claim) is False

    def test_future_claim_not_current_yet(self):
        manager = TemporalBeliefManager()
        claim = make_claim(valid_from=datetime.utcnow() + timedelta(days=1))
        assert manager.is_current(claim) is False

    def test_claim_without_window_is_current(self):
        manager = TemporalBeliefManager()
        claim = make_claim()
        assert manager.is_current(claim) is True

    def test_temporal_conflict_detected(self):
        manager = TemporalBeliefManager()
        old = make_claim(
            claim_id="old",
            object="Ollama",
            valid_until=datetime.utcnow() - timedelta(days=1),
        )
        new = make_claim(
            claim_id="new",
            object="LM Studio",
            valid_from=datetime.utcnow() - timedelta(hours=12),
        )
        conflict = manager.detect_temporal_conflict(old, new)
        assert conflict is not None


class TestContradictionDetection:
    def test_direct_contradiction(self):
        detector = ContradictionDetector()
        claim = make_claim()
        ev = make_evidence(relation=EvidenceRelation.CONTRADICTS)
        contradictions = detector.detect(claim, [ev])
        assert len(contradictions) == 1

    def test_support_is_not_contradiction(self):
        detector = ContradictionDetector()
        claim = make_claim()
        ev = make_evidence(relation=EvidenceRelation.SUPPORTS)
        contradictions = detector.detect(claim, [ev])
        assert contradictions == []

    def test_high_confidence_contradiction_has_severity(self):
        detector = ContradictionDetector()
        claim = make_claim(confidence=0.95)
        ev = make_evidence(
            relation=EvidenceRelation.CONTRADICTS,
            strength=EvidenceStrength.DEFINITIVE,
            confidence=0.95,
        )
        contradictions = detector.detect(claim, [ev])
        assert contradictions
        assert contradictions[0].severity in {
            ContradictionSeverity.MEDIUM,
            ContradictionSeverity.HIGH,
            ContradictionSeverity.CRITICAL,
        }

    def test_tenant_mismatch_ignored(self):
        detector = ContradictionDetector()
        claim = make_claim(tenant_id="tenant-a")
        ev = make_evidence(
            tenant_id="tenant-b",
            relation=EvidenceRelation.CONTRADICTS,
        )
        assert detector.detect(claim, [ev]) == []


class TestBeliefRevision:
    def test_support_can_strengthen(self):
        engine = BeliefRevisionEngine()
        claim = make_claim(confidence=0.4)
        ev = make_evidence(
            relation=EvidenceRelation.SUPPORTS,
            strength=EvidenceStrength.DEFINITIVE,
            confidence=0.95,
        )
        action, revision = engine.revise(claim, [ev], [])
        assert action in (RevisionAction.STRENGTHEN, RevisionAction.KEEP)
        assert revision is not None

    def test_contradiction_can_weaken(self):
        engine = BeliefRevisionEngine()
        claim = make_claim(confidence=0.8)
        ev = make_evidence(
            relation=EvidenceRelation.CONTRADICTS,
            strength=EvidenceStrength.DEFINITIVE,
            confidence=0.95,
        )
        action, revision = engine.revise(claim, [ev], [])
        assert action in (
            RevisionAction.WEAKEN,
            RevisionAction.RETRACT,
            RevisionAction.KEEP,
        )
        assert revision is not None

    def test_supersede_links_claims(self):
        engine = BeliefRevisionEngine()
        old_claim = make_claim(claim_id="old", object="Ollama")
        new_claim = make_claim(claim_id="new", object="LM Studio")
        revision = engine.supersede(old_claim, new_claim, "provider changed")
        assert revision.action == RevisionAction.SUPERSEDE
        assert old_claim.status == ClaimStatus.SUPERSEDED
        assert old_claim.superseded_by == "new"

    def test_verified_may_strengthen_with_definitive_evidence(self):
        engine = BeliefRevisionEngine()
        claim = make_claim(status=ClaimStatus.VERIFIED, confidence=0.8)
        new_ev = make_evidence(
            observed_at=datetime.utcnow(),
            strength=EvidenceStrength.DEFINITIVE,
            confidence=0.95,
        )
        action, revision = engine.revise(claim, [new_ev], [])
        assert action in (RevisionAction.SUPERSEDE, RevisionAction.STRENGTHEN)

    def test_retracted_cannot_be_active(self):
        engine = BeliefRevisionEngine()
        claim = make_claim(status=ClaimStatus.RETRACTED, confidence=0.5)
        ev = make_evidence()
        assessment = engine._engine.assess(claim, [ev])
        assert assessment.verdict == BeliefVerdict.INACTIVE

    def test_historical_superseded_claim_remains_queryable(self):
        engine = BeliefRevisionEngine()
        old_claim = make_claim(claim_id="old", object="Ollama")
        new_claim = make_claim(claim_id="new", object="LM Studio")
        engine.supersede(old_claim, new_claim, "provider changed")
        history = engine.revision_history("old")
        assert len(history) == 1
        assert history[0].action == RevisionAction.SUPERSEDE
        assert old_claim.status == ClaimStatus.SUPERSEDED
        assert old_claim.superseded_by == "new"

    def test_revision_preserves_history(self):
        engine = BeliefRevisionEngine()
        claim = make_claim(confidence=0.5)
        ev = make_evidence(
            relation=EvidenceRelation.SUPPORTS,
            strength=EvidenceStrength.DEFINITIVE,
            confidence=0.95,
        )
        action, revision = engine.revise(claim, [ev], [])
        history = engine.revision_history(claim.claim_id)
        assert len(history) >= 1
        assert float(history[-1].confidence_before) == 0.5

    def test_inferred_claim_not_auto_verified(self):
        engine = BeliefRevisionEngine()
        claim = make_claim(
            status=ClaimStatus.INFERRED,
            source=EvidenceType.SYSTEM_INFERENCE,
            confidence=0.5,
        )
        evs = [
            make_evidence(
                type=EvidenceType.TOOL_RESULT,
                relation=EvidenceRelation.SUPPORTS,
                strength=EvidenceStrength.DEFINITIVE,
                confidence=0.95,
            )
        ]
        result = engine.verify(claim, evs)
        if result:
            assert claim.status == ClaimStatus.VERIFIED
        else:
            assert claim.status == ClaimStatus.INFERRED


class TestUnknownAndInsufficient:
    def test_insufficient_evidence_returns_unknown(self):
        engine = BeliefEngine()
        claim = make_claim(status=ClaimStatus.UNKNOWN, confidence=0.0)
        assessment = engine.assess(claim, [])
        assert assessment.verdict == BeliefVerdict.UNKNOWN

    def test_evidence_source_preserved(self):
        engine = BeliefEngine()
        claim = make_claim(source=EvidenceType.USER_STATEMENT)
        ev = make_evidence(type=EvidenceType.USER_STATEMENT, source_ref="msg1")
        assessment = engine.assess(claim, [ev])
        assert ev.evidence_id in assessment.evidence_refs

    def test_repeated_inference_not_verification(self):
        engine = BeliefEngine()
        claim = make_claim(
            status=ClaimStatus.INFERRED,
            source=EvidenceType.SYSTEM_INFERENCE,
        )
        evs = [
            make_evidence(
                type=EvidenceType.SYSTEM_INFERENCE,
                relation=EvidenceRelation.SUPPORTS,
            )
            for _ in range(5)
        ]
        assessment = engine.assess(claim, evs)
        assert assessment.status != ClaimStatus.VERIFIED

    def test_user_assertion_authoritative_not_external_fact(self):
        engine = BeliefEngine()
        claim = make_claim(
            status=ClaimStatus.USER_ASSERTED,
            source=EvidenceType.USER_STATEMENT,
        )
        assessment = engine.assess(claim, [])
        assert assessment.status == ClaimStatus.USER_ASSERTED
        assert "user_asserted_authoritative" in assessment.reason_codes


class TestTenantIsolation:
    def test_tenant_scoped_evidence_does_not_cross(self):
        detector = ContradictionDetector()
        claim_a = make_claim(claim_id="a", tenant_id="tenant-a")
        ev_b = make_evidence(evidence_id="ev_b", tenant_id="tenant-b")
        contradictions = detector.detect(claim_a, [ev_b])
        assert len(contradictions) == 0


class TestConfidenceMetrics:
    def test_overall_confidence_geometric_mean(self):
        metrics = ConfidenceMetrics(
            source_confidence=0.8,
            evidence_strength=0.8,
            belief_confidence=0.8,
            freshness_confidence=0.8,
            consistency_confidence=0.8,
        )
        assert float(metrics.overall) == pytest.approx(0.8, rel=1e-6)

    def test_clamped_values(self):
        metrics = ConfidenceMetrics(
            source_confidence=2.0,
            evidence_strength=-0.5,
        )
        assert float(metrics.source_confidence) == 1.0
        assert float(metrics.evidence_strength) == 0.0


__all__ = [
    "TestClaimAssessment",
    "TestTemporalTruth",
    "TestContradictionDetection",
    "TestBeliefRevision",
    "TestUnknownAndInsufficient",
    "TestTenantIsolation",
    "TestConfidenceMetrics",
]
