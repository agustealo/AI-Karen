"""Belief assessment engine for AI-Karen reasoning.

Evaluates claims against evidence using pure cognitive logic only.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .contracts import (
    EVIDENCE_STRENGTH_WEIGHTS,
    SOURCE_CREDIBILITY,
    STALENESS_THRESHOLD_HOURS,
    BeliefAssessment,
    BeliefClaim,
    BeliefContradiction,
    BeliefVerdict,
    ClaimStatus,
    ConfidenceMetrics,
    ContradictionKind,
    ContradictionNature,
    Evidence,
    EvidenceRelation,
    EvidenceType,
    UncertaintySource,
    make_contradiction_id,
)

logger = logging.getLogger(__name__)


class BeliefEngine:
    """Assess belief claims using evidence and confidence dimensions."""

    def __init__(self, staleness_threshold_hours: float = STALENESS_THRESHOLD_HOURS) -> None:
        self._staleness_threshold_hours = staleness_threshold_hours

    def assess(self, claim: BeliefClaim, evidence: list[Evidence]) -> BeliefAssessment:
        metrics = ConfidenceMetrics()
        reason_codes: list[str] = []
        uncertainty_sources: list[UncertaintySource] = []
        evidence_refs = [item.evidence_id for item in evidence]

        metrics.source_confidence = SOURCE_CREDIBILITY.get(claim.source, 0.5)
        if claim.source == EvidenceType.SYSTEM_INFERENCE:
            uncertainty_sources.append(UncertaintySource.INFERENCE_ONLY)
        if claim.source == EvidenceType.MEMORY:
            uncertainty_sources.append(UncertaintySource.SINGLE_SOURCE)

        supporting = [
            item
            for item in evidence
            if item.relation in (EvidenceRelation.SUPPORTS, EvidenceRelation.CORROBORATES)
        ]
        contradicting = [
            item
            for item in evidence
            if item.relation in (EvidenceRelation.CONTRADICTS, EvidenceRelation.WEAKENS)
        ]

        metrics.evidence_strength = self._aggregate_evidence_strength(supporting)
        if not supporting:
            uncertainty_sources.append(UncertaintySource.NEW_CLAIM)
        if contradicting:
            uncertainty_sources.append(UncertaintySource.CONTRADICTORY_EVIDENCE)

        metrics.belief_confidence = self._belief_confidence(claim, supporting, contradicting)
        metrics.freshness_confidence, stale = self._freshness(claim, evidence)
        if stale:
            uncertainty_sources.append(UncertaintySource.STALE_EVIDENCE)

        metrics.consistency_confidence, contradictions = self._consistency(claim, contradicting)
        overall = metrics.overall
        if overall < 0.3:
            uncertainty_sources.append(UncertaintySource.LOW_SOURCE_CREDENCE)

        verdict = self._verdict(claim, evidence, float(overall), contradictions)

        if claim.status == ClaimStatus.INFERRED:
            reason_codes.append("inferred_not_verified")
        elif claim.status == ClaimStatus.USER_ASSERTED:
            reason_codes.append("user_asserted_authoritative")
        elif claim.status == ClaimStatus.VERIFIED:
            reason_codes.append("verified")
        elif claim.status == ClaimStatus.OBSERVED:
            reason_codes.append("observed")
        if contradictions:
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
            contradictions=contradictions,
            verdict=verdict,
        )

    def compare(
        self,
        claim_a: BeliefClaim,
        claim_b: BeliefClaim,
        evidence: list[Evidence],
    ) -> str:
        if claim_a.subject == claim_b.subject and claim_a.predicate == claim_b.predicate:
            return "same" if claim_a.object == claim_b.object else "contradictory"
        if set(claim_a.evidence_ids) & set(claim_b.evidence_ids):
            return "corroborating"
        return "independent"

    def assess_batch(
        self,
        claims: list[BeliefClaim],
        evidence_map: dict[str, list[Evidence]],
    ) -> list[BeliefAssessment]:
        return [self.assess(claim, evidence_map.get(claim.claim_id, [])) for claim in claims]

    def _aggregate_evidence_strength(self, evidence: list[Evidence]) -> float:
        if not evidence:
            return 0.0
        total = 0.0
        weight_sum = 0.0
        for item in evidence:
            weight = EVIDENCE_STRENGTH_WEIGHTS.get(item.strength, 0.5)
            total += weight * item.confidence
            weight_sum += weight
        return total / weight_sum if weight_sum > 0 else 0.0

    def _belief_confidence(
        self,
        claim: BeliefClaim,
        supporting: list[Evidence],
        contradicting: list[Evidence],
    ) -> float:
        supporting_weight = self._aggregate_evidence_strength(supporting) if supporting else 0.0
        contradicting_weight = self._aggregate_evidence_strength(contradicting) if contradicting else 0.0
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

        if supporting_weight > 0:
            base = min(1.0, base + 0.2 * supporting_weight)
        if contradicting_weight > 0:
            base = max(0.0, base - 0.3 * contradicting_weight)
        return max(0.0, min(1.0, base))

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _freshness(
        self,
        claim: BeliefClaim,
        evidence: list[Evidence],
    ) -> tuple[float, bool]:
        now = datetime.now(timezone.utc)
        reference_time: datetime | None = None
        for item in evidence:
            if item.observed_at is not None:
                observed = self._utc(item.observed_at)
                if reference_time is None or observed > reference_time:
                    reference_time = observed
        if reference_time is None:
            for candidate in (
                claim.temporal.last_verified_at,
                claim.temporal.observed_at,
                claim.temporal.asserted_at,
            ):
                if candidate is not None:
                    reference_time = self._utc(candidate)
                    break
        if reference_time is None:
            return 0.5, True
        age_hours = (now - reference_time).total_seconds() / 3600.0
        threshold = self._staleness_threshold_hours
        freshness = max(0.0, min(1.0, 1.0 - age_hours / threshold)) if threshold > 0 else 0.5
        return freshness, age_hours > threshold

    def _consistency(
        self,
        claim: BeliefClaim,
        contradicting: list[Evidence],
    ) -> tuple[float, list[BeliefContradiction]]:
        contradictions = [
            BeliefContradiction(
                contradiction_id=make_contradiction_id(),
                claim_a_id=claim.claim_id,
                claim_b_id=None,
                kind=ContradictionKind.SOURCE_DISAGREEMENT,
                nature=ContradictionNature.CONTRADICTION,
                severity="medium",
                description=f"Evidence {item.evidence_id} contradicts claim",
                evidence_refs=[item.evidence_id],
                tenant_id=claim.tenant_id,
            )
            for item in contradicting
        ]
        if not contradicting:
            return 1.0, contradictions
        return max(0.0, 1.0 - len(contradicting) * 0.3), contradictions

    def _verdict(
        self,
        claim: BeliefClaim,
        evidence: list[Evidence],
        confidence: float,
        contradictions: list[BeliefContradiction],
    ) -> BeliefVerdict:
        if claim.status in (ClaimStatus.RETRACTED, ClaimStatus.SUPERSEDED):
            return BeliefVerdict.INACTIVE
        if contradictions and not evidence:
            return BeliefVerdict.CONFLICTING_EVIDENCE
        if not evidence:
            return (
                BeliefVerdict.UNKNOWN
                if claim.status == ClaimStatus.UNKNOWN
                else BeliefVerdict.INSUFFICIENT_EVIDENCE
            )
        if contradictions:
            return BeliefVerdict.CONFLICTING
        if confidence < 0.2:
            return BeliefVerdict.INSUFFICIENT_EVIDENCE
        if claim.temporal.is_expired():
            return BeliefVerdict.STALE_EVIDENCE
        return BeliefVerdict.ACTIVE


__all__ = ["BeliefEngine"]
