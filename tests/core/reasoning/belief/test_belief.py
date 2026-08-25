"""
Tests for COG-BELIEF-1 belief / uncertainty / contradiction engine.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from ai_karen_engine.core.reasoning.belief.contracts import (
    BeliefClaim,
    BeliefVerdict,
    ClaimStatus,
    ClaimScope,
    ClaimTemporalValidity,
    ConfidenceMetrics,
    ContradictionKind,
    ContradictionNature,
    Evidence,
    EvidenceRelation,
    EvidenceStrength,
    EvidenceType,
    RevisionAction,
    make_claim_id,
    make_evidence_id,
)
from ai_karen_engine.core.reasoning.belief.assessment import BeliefEngine
from ai_karen_engine.core.reasoning.belief.contradiction import ContradictionDetector
from ai_karen_engine.core.reasoning.belief.revision import BeliefRevisionEngine
from ai_karen_engine.core.reasoning.belief.temporal import TemporalReasoner


def make_temporal(
    asserted_at: datetime | None = None,
    observed_at: datetime | None = None,
    last_verified_at: datetime | None = None,
    valid_until: datetime | None = None,
) -> ClaimTemporalValidity:
    return ClaimTemporalValidity(
        asserted_at=asserted_at,
        observed_at=observed_at,
        valid_from=None,
        valid_until=valid_until,
        last_verified_at=last_verified_at,
    )


def make_claim(
    claim_id: str = "claim_1",
    subject: str = "preferred_provider",
    predicate: str = "is",
    obj: str = "Ollama",
    status: ClaimStatus = ClaimStatus.OBSERVED,
    source: EvidenceType = EvidenceType.OBSERVATION,
    confidence: float = 0.8,
    tenant_id: str = "t1",
    user_id: str = "u1",
    asserted_at: datetime | None = None,
    observed_at: datetime | None = None,
    last_verified_at: datetime | None = None,
    valid_until: datetime | None = None,
) -> BeliefClaim:
    now = datetime.utcnow()
    asserted_at = asserted_at or now
    observed_at = observed_at or now
    last_verified_at = last_verified_at or now
    temporal = make_temporal(
        asserted_at=asserted_at,
        observed_at=observed_at,
        last_verified_at=last_verified_at,
        valid_until=valid_until,
    )
    return BeliefClaim(
        claim_id=claim_id,
        subject=subject,
        predicate=predicate,
        object=obj,
        status=status,
        source=source,
        source_ref="ref-1",
        scope=ClaimScope.USER,
        confidence=confidence,
        tenant_id=tenant_id,
        user_id=user_id,
        claim_format="triple",
        provenance="test",
        evidence_ids=[],
        contradictions=[],
        superseded_by=None,
        version=1,
        temporal=temporal,
    )


def make_evidence(
    evidence_id: str = "ev1",
    etype: EvidenceType = EvidenceType.OBSERVATION,
    relation: EvidenceRelation = EvidenceRelation.SUPPORTS,
    strength: EvidenceStrength = EvidenceStrength.MODERATE,
    confidence: float = 0.8,
    observed_at: datetime | None = None,
    tenant_id: str = "t1",
    user_id: str = "u1",
    source: str = "test_source",
    source_ref: str = "ref",
    content: str = "evidence content",
) -> Evidence:
    observed_at = observed_at or datetime.utcnow()
    return Evidence(
        evidence_id=evidence_id,
        type=etype,
        source=source,
        source_ref=source_ref,
        content=content,
        strength=strength,
        relation=relation,
        confidence=confidence,
        observed_at=observed_at,
        tenant_id=tenant_id,
        user_id=user_id,
    )


class TestClaimAssessment:
    def test_inferred_claim_is_not_verified(self):
        engine = BeliefEngine()
        claim = make_claim(
            status=ClaimStatus.INFERRED,
            source=EvidenceType.SYSTEM_INFERENCE,
            confidence=0.6,
        )
        ev = make_evidence(etype=EvidenceType.SYSTEM_INFERENCE)
        assessment = engine.assess(claim, [ev])
        assert assessment.status != ClaimStatus.VERIFIED
        assert "inferred_not_verified" in assessment.reason_codes

    def test_user_assertion_and_system_inference_distinguishable(self):
        engine = BeliefEngine()
        user_claim = make_claim(
            status=ClaimStatus.USER_ASSERTED,
            source=EvidenceType.USER_STATEMENT,
        )
        inferred_claim = make_claim(
            status=ClaimStatus.INFERRED,
            source=EvidenceType.SYSTEM_INFERENCE,
        )
        user_assessment = engine.assess(user_claim, [])
        inferred_assessment = engine.assess(inferred_claim, [])
        assert user_assessment.status == ClaimStatus.USER_ASSERTED
        assert inferred_assessment.status == ClaimStatus.INFERRED
        assert "user_asserted_authoritative" in user_assessment.reason_codes

    def test_strong_corroborating_evidence_raises_confidence(self):
        engine = BeliefEngine()
        claim = make_claim(
            status=ClaimStatus.OBSERVED,
            source=EvidenceType.OBSERVATION,
            confidence=0.5,
        )
        evs = [
            make_evidence(evidence_id=f"ev{i}", relation=EvidenceRelation.CORROBORATES,
                          strength=EvidenceStrength.STRONG, confidence=0.9)
            for i in range(3)
        ]
        assessment = engine.assess(claim, evs)
        assert assessment.overall_confidence > 0.5

    def test_contradictory_evidence_lowers_confidence(self):
        engine = BeliefEngine()
        claim = make_claim(
            status=ClaimStatus.OBSERVED,
            source=EvidenceType.OBSERVATION,
            confidence=0.9,
        )
        supporting = [make_evidence(evidence_id="sup1", relation=EvidenceRelation.SUPPORTS,
                                     strength=EvidenceStrength.STRONG, confidence=0.9)]
        contradicting = [make_evidence(evidence_id="con1", relation=EvidenceRelation.CONTRADICTS,
                                       strength=EvidenceStrength.STRONG, confidence=0.9)]
        assessment = engine.assess(claim, supporting + contradicting)
        assert assessment.overall_confidence < 0.9

    def test_confidence_stays_within_valid_range(self):
        engine = BeliefEngine()
        claim = make_claim(confidence=1.0)
        assessment = engine.assess(claim, [])
        assert 0.0 <= assessment.overall_confidence <= 1.0
        assert 0.0 <= assessment.confidence_metrics.overall <= 1.0

    def test_conflicting_claims_can_coexist(self):
        engine = BeliefEngine()
        claim_a = make_claim(
            claim_id="a", object="Ollama",
            asserted_at=datetime.utcnow() - timedelta(days=1),
        )
        claim_b = make_claim(
            claim_id="b", object="LM Studio",
            asserted_at=datetime.utcnow() - timedelta(days=2),
        )
        assessment_a = engine.assess(claim_a, [])
        assessment_b = engine.assess(claim_b, [])
        assert assessment_a.claim_id == "a"
        assert assessment_b.claim_id == "b"


class TestTemporalTruth:
    def test_temporal_change_can_supersede_without_contradiction(self):
        detector = ContradictionDetector()
        old_claim = make_claim(
            claim_id="old", object="Ollama",
            asserted_at=datetime.utcnow() - timedelta(days=40),
        )
        new_claim = make_claim(
            claim_id="new", object="LM Studio",
            asserted_at=datetime.utcnow(),
        )
        nature, superseded = detector.resolve_temporal(
            old_claim, new_claim.observed_at or datetime.utcnow()
        )
        assert nature == ContradictionNature.CHANGE_OVER_TIME

    def test_stale_evidence_reduces_current_applicability(self):
        engine = BeliefEngine()
        claim = make_claim(
            status=ClaimStatus.OBSERVED,
            source=EvidenceType.MEMORY,
            observed_at=datetime.utcnow() - timedelta(days=40),
            last_verified_at=datetime.utcnow() - timedelta(days=40),
        )
        ev = make_evidence(
            observed_at=datetime.utcnow() - timedelta(days=40),
        )
        assessment = engine.assess(claim, [ev])
        assert assessment.verdict in (
            BeliefVerdict.STALE_EVIDENCE,
            BeliefVerdict.UNKNOWN,
            BeliefVerdict.INSUFFICIENT_EVIDENCE,
        )

    def test_invalid_time_window(self):
        reasoner = TemporalReasoner()
        claim = make_claim()
        claim.temporal.valid_from = datetime.utcnow() + timedelta(days=1)
        assert not reasoner.is_valid(claim)

    def test_expired_claim_invalid(self):
        reasoner = TemporalReasoner()
        claim = make_claim()
        claim.temporal.valid_until = datetime.utcnow() - timedelta(hours=1)
        assert not reasoner.is_valid(claim)
        assert claim.temporal.is_expired


class TestContradictionDetection:
    def test_direct_contradiction_detected(self):
        detector = ContradictionDetector()
        claim = make_claim(
            subject="preferred_provider", object="Ollama",
            status=ClaimStatus.OBSERVED,
        )
        ev = make_evidence(
            relation=EvidenceRelation.CONTRADICTS,
            content="preferred_provider is LM Studio",
            strength=EvidenceStrength.DEFINITIVE,
        )
        contradictions = detector.detect(claim, [ev])
        assert len(contradictions) > 0
        assert contradictions[0].nature == ContradictionNature.CONTRADICTION

    def test_contradicting_evidence_lowers_confidence(self):
        engine = BeliefEngine()
        claim = make_claim(confidence=0.9)
        supporting = [make_evidence(relation=EvidenceRelation.SUPPORTS)]
        contradicting = [make_evidence(relation=EvidenceRelation.CONTRADICTS,
                                       evidence_id="con1")]
        assessment = engine.assess(claim, supporting + contradicting)
        assert assessment.overall_confidence < 0.9

    def test_contradiction_between_claims(self):
        detector = ContradictionDetector()
        claim_a = make_claim(claim_id="a", object="Ollama",
                             asserted_at=datetime.utcnow() - timedelta(days=1))
        claim_b = make_claim(claim_id="b", object="LM Studio",
                             asserted_at=datetime.utcnow())
        result = detector.compare_claims(claim_a, claim_b)
        assert result is not None
        assert result.kind == ContradictionKind.DIRECT


class TestBeliefRevision:
    def test_strong_evidence_supersedes(self):
        engine = BeliefRevisionEngine()
        claim = make_claim(
            status=ClaimStatus.OBSERVED,
            object="cloud-only",
            confidence=0.8,
            asserted_at=datetime.utcnow() - timedelta(days=40),
        )
        new_ev = make_evidence(
            evidence_id="new_ev",
            relation=EvidenceRelation.SUPERSEDES,
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
        assert history[-1].confidence_before == 0.5

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
        ev = make_evidence(etype=EvidenceType.USER_STATEMENT, source_ref="msg1")
        assessment = engine.assess(claim, [ev])
        assert ev.evidence_id in assessment.evidence_refs

    def test_repeated_inference_not_verification(self):
        engine = BeliefEngine()
        claim = make_claim(
            status=ClaimStatus.INFERRED,
            source=EvidenceType.SYSTEM_INFERENCE,
        )
        evs = [
            make_evidence(etype=EvidenceType.SYSTEM_INFERENCE,
                          relation=EvidenceRelation.SUPPORTS)
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
        assert metrics.overall == pytest.approx(0.8, rel=1e-6)

    def test_clamped_values(self):
        metrics = ConfidenceMetrics(
            source_confidence=2.0,
            evidence_strength=-0.5,
        )
        assert metrics.source_confidence == 1.0
        assert metrics.evidence_strength == 0.0


__all__ = [
    "TestClaimAssessment",
    "TestTemporalTruth",
    "TestContradictionDetection",
    "TestBeliefRevision",
    "TestUnknownAndInsufficient",
    "TestTenantIsolation",
    "TestConfidenceMetrics",
]
