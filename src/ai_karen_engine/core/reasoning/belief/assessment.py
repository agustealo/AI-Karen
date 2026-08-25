"""
Belief assessment engine for AI-Karen reasoning.

Evaluates claims against evidence to produce multi-dimensional confidence
assessments.  Pure logic only -- no database fetching, no provider calls.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .contracts import (
    ClaimStatus,
    Evidence,
    EvidenceRelation,
    EvidenceStrength,
    EvidenceType,
    BeliefAssessment,
    BeliefClaim,
    BeliefContradiction,
    BeliefVerdict,
    ConfidenceMetrics,
    ClaimScope,
    UncertaintySource,
    EVIDENCE_STRENGTH_WEIGHTS,
    SOURCE_CREDIBILITY,
    STALENESS_THRESHOLD_HOURS,
    make_contradiction_id,
)

logger = logging.getLogger(__name__)


class BeliefEngine:
    """Assesses belief claims using evidence and confidence dimensions."""

    def __init__(self, staleness_threshold_hours: float = STALENESS_THRESHOLD_HOURS) -> None:
        self._staleness_threshold_hours = staleness_threshold_hours

    def assess(
        self,
        claim: BeliefClaim,
        evidence: List[Evidence],
    ) -> BeliefAssessment:
        """Assess a claim given a collection of evidence items."""
        metrics = ConfidenceMetrics()
        reason_codes: List[str] = []
        uncertainty_sources: List[UncertaintySource] = []
        evidence_refs: List[str] = [e.evidence_id for e in evidence]
        contradictions_list: List[BeliefContradiction] = []

        # Source confidence
        metrics.source_confidence = SOURCE_CREDIBILITY.get(claim.source, 0.5)
        if claim.source == EvidenceType.SYSTEM_INFERENCE:
            uncertainty_sources.append(UncertaintySource.INFERENCE_ONLY)
        if claim.source == EvidenceType.MEMORY:
            uncertainty_sources.append(UncertaintySource.SINGLE_SOURCE)

        # Evidence strength (aggregate of supporting evidence)
        supporting = [e for e in evidence if e.relation == EvidenceRelation.SUPPORTS or e.relation == EvidenceRelation.CORROBORATES]
        contradicting = [e for e in evidence if e.relation == EvidenceRelation.CONTRADICTS or e.relation == EvidenceRelation.WEAKENS]

        metrics.evidence_strength = self._aggregate_evidence_strength(supporting)
        if not supporting:
            uncertainty_sources.append(UncertaintySource.NEW_CLAIM)
        if contradicting:
            uncertainty_sources.append(UncertaintySource.CONTRADICTORY_EVIDENCE)

        # Belief confidence (synthesis of evidence and source)
        metrics.belief_confidence = self._belief_confidence(claim, supporting, contradicting)

        # Freshness confidence
        metrics.freshness_confidence, stale = self._freshness(claim, evidence)
        if stale:
            uncertainty_sources.append(UncertaintySource.STALE_EVIDENCE)
        if not uncertainty_sources:
            uncertainty_sources.append(UncertaintySource.INFERENCE_ONLY)

        # Consistency confidence
        metrics.consistency_confidence, contradictions_list = self._consistency(claim, contradicting)

        overall = metrics.overall
        if overall < 0.3:
            uncertainty_sources.append(UncertaintySource.LOW_SOURCE_CREDENCE)

        verdict = self._verdict(claim, evidence, overall, contradictions_list)

        if claim.status == ClaimStatus.INFERRED:
            reason_codes.append("inferred_not_verified")
        if claim.status == ClaimStatus.USER_ASSERTED:
            reason_codes.append("user_asserted_authoritative")
        if claim.status == ClaimStatus.VERIFIED:
            reason_codes.append("verified")
        if claim.status == ClaimStatus.OBSERVED:
            reason_codes.append("observed")
        if contradictions_list:
            reason_codes.append("has_contradictions")
        if not reason_codes:
            reason_codes.append("insufficient_evidence")

        return BeliefAssessment(
            claim_id=claim.claim_id,
            status=claim.status,
            overall_confidence=overall,
            confidence_metrics=metrics,
            reason_codes=reason_codes,
            evidence_refs=evidence_refs,
            uncertainty_sources=uncertainty_sources,
            contradictions=contradictions_list,
            verdict=verdict,
        )

    def compare(
        self,
        claim_a: BeliefClaim,
        claim_b: BeliefClaim,
        evidence: List[Evidence],
    ) -> str:
        """Compare two claims and return their relationship."""
        if claim_a.subject == claim_b.subject and claim_a.predicate == claim_b.predicate:
            if claim_a.object == claim_b.object:
                return "same"
            return "contradictory"
        overlap = set(claim_a.evidence_ids) & set(claim_b.evidence_ids)
        if overlap:
            return "corroborating"
        return "independent"

    def assess_batch(
        self,
        claims: List[BeliefClaim],
        evidence_map: Dict[str, List[Evidence]],
    ) -> List[BeliefAssessment]:
        """Assess multiple claims efficiently."""
        return [self.assess(c, evidence_map.get(c.claim_id, [])) for c in claims]

    # ---- private helpers ----

    def _aggregate_evidence_strength(self, evidence: List[Evidence]) -> float:
        if not evidence:
            return 0.0
        total = 0.0
        weight_sum = 0.0
        for e in evidence:
            weight = EVIDENCE_STRENGTH_WEIGHTS.get(e.strength, 0.5)
            strength = e.confidence
            total += weight * strength
            weight_sum += weight
        return total / weight_sum if weight_sum > 0 else 0.0

    def _belief_confidence(
        self,
        claim: BeliefClaim,
        supporting: List[Evidence],
        contradicting: List[Evidence],
    ) -> float:
        sup_weight = self._aggregate_evidence_strength(supporting) if supporting else 0.0
        con_weight = self._aggregate_evidence_strength(contradicting) if contradicting else 0.0

        source_weight = SOURCE_CREDIBILITY.get(claim.source, 0.5)

        if claim.status == ClaimStatus.VERIFIED:
            base = 0.8 + 0.2 * source_weight
        elif claim.status == ClaimStatus.USER_ASSERTED:
            base = 0.6 + 0.3 * source_weight
        elif claim.status == ClaimStatus.OBSERVED:
            base = 0.4 + 0.4 * source_weight
        elif claim.status == ClaimStatus.INFERRED:
            base = 0.2 + 0.3 * source_weight
        else:
            base = 0.3 + 0.3 * source_weight

        if sup_weight > 0:
            base = min(1.0, base + 0.2 * sup_weight)
        if con_weight > 0:
            base = max(0.0, base - 0.3 * con_weight)

        return max(0.0, min(1.0, base))

    def _freshness(
        self,
        claim: BeliefClaim,
        evidence: List[Evidence],
    ) -> tuple[float, bool]:
        """Compute freshness confidence and detect staleness."""
        now = datetime.utcnow()
        reference_time: Optional[datetime] = None

        for e in evidence:
            if e.observed_at is not None:
                if reference_time is None or e.observed_at > reference_time:
                    reference_time = e.observed_at

        if reference_time is None:
            if claim.temporal.last_verified_at is not None:
                reference_time = claim.temporal.last_verified_at
            elif claim.temporal.observed_at is not None:
                reference_time = claim.temporal.observed_at
            elif claim.temporal.asserted_at is not None:
                reference_time = claim.temporal.asserted_at

        if reference_time is None:
            return 0.5, True

        age_hours = (now - reference_time).total_seconds() / 3600.0
        threshold = self._staleness_threshold_hours
        freshness = max(0.0, min(1.0, 1.0 - age_hours / threshold)) if threshold > 0 else 0.5
        is_stale = age_hours > threshold
        return freshness, is_stale

    def _consistency(
        self,
        claim: BeliefClaim,
        contradicting: List[Evidence],
    ) -> tuple[float, List[BeliefContradiction]]:
        """Compute consistency confidence and collect contradictions."""
        contradictions: List[BeliefContradiction] = []
        for e in contradicting:
            contradictions.append(
                BeliefContradiction(
                    contradiction_id=make_contradiction_id(),
                    claim_a_id=claim.claim_id,
                    claim_b_id=None,
                    kind=contradicting[0].type if contradicting else EvidenceType.OBSERVATION,
                    nature="contradiction",
                    severity="medium",
                    description=f"Evidence {e.evidence_id} contradicts claim",
                    evidence_refs=[e.evidence_id],
                    tenant_id=claim.tenant_id,
                )
            )

        if not contradicting:
            return 1.0, contradictions
        consistency = max(0.0, 1.0 - len(contradicting) * 0.3)
        return consistency, contradictions

    def _verdict(
        self,
        claim: BeliefClaim,
        evidence: List[Evidence],
        confidence: float,
        contradictions: List[BeliefContradiction],
    ) -> BeliefVerdict:
        """Determine the final verdict."""
        if claim.status == ClaimStatus.RETRACTED:
            return BeliefVerdict.INACTIVE
        if claim.status == ClaimStatus.SUPERSEDED:
            return BeliefVerdict.INACTIVE
        if contradictions and not evidence:
            return BeliefVerdict.CONFLICTING_EVIDENCE
        if not evidence:
            if claim.status == ClaimStatus.UNKNOWN:
                return BeliefVerdict.UNKNOWN
            return BeliefVerdict.INSUFFICIENT_EVIDENCE
        if contradictions:
            return BeliefVerdict.CONFLICTING
        if confidence < 0.2:
            return BeliefVerdict.INSUFFICIENT_EVIDENCE
        if claim.temporal.is_expired:
            return BeliefVerdict.STALE_EVIDENCE
        return BeliefVerdict.ACTIVE


__all__ = ["BeliefEngine"]
