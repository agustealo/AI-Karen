"""Belief / uncertainty / contradiction engine for AI-Karen reasoning.

Exports canonical contracts and pure-logic engines for belief assessment,
contradiction detection, temporal reasoning, and belief revision.
"""

from __future__ import annotations

from .assessment import BeliefEngine
from .contracts import (
    EVIDENCE_STRENGTH_WEIGHTS,
    SOURCE_CREDIBILITY,
    STALENESS_THRESHOLD_HOURS,
    BeliefAssessment,
    BeliefClaim,
    BeliefContradiction,
    BeliefRevision,
    BeliefVerdict,
    ClaimComparison,
    ClaimScope,
    ClaimStatus,
    ClaimTemporalValidity,
    ConfidenceDimension,
    ConfidenceMetrics,
    ContradictionKind,
    ContradictionNature,
    Evidence,
    EvidenceRelation,
    EvidenceStrength,
    EvidenceType,
    RevisionAction,
    UncertaintySource,
    make_claim_id,
    make_contradiction_id,
    make_evidence_id,
    make_revision_id,
)
from .contradiction import ContradictionDetector
from .revision import BeliefRevisionEngine
from .temporal import TemporalReasoner

__all__ = [
    "EVIDENCE_STRENGTH_WEIGHTS",
    "SOURCE_CREDIBILITY",
    "STALENESS_THRESHOLD_HOURS",
    "BeliefAssessment",
    "BeliefClaim",
    "BeliefContradiction",
    "BeliefEngine",
    "BeliefRevision",
    "BeliefRevisionEngine",
    "BeliefVerdict",
    "ClaimComparison",
    "ClaimScope",
    "ClaimStatus",
    "ClaimTemporalValidity",
    "ConfidenceDimension",
    "ConfidenceMetrics",
    "ContradictionDetector",
    "ContradictionKind",
    "ContradictionNature",
    "Evidence",
    "EvidenceRelation",
    "EvidenceStrength",
    "EvidenceType",
    "RevisionAction",
    "TemporalReasoner",
    "UncertaintySource",
    "make_claim_id",
    "make_contradiction_id",
    "make_evidence_id",
    "make_revision_id",
]
