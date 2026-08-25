"""Belief / uncertainty / contradiction engine for AI-Karen reasoning.

Exports canonical contracts and pure-logic engines for belief assessment,
contradiction detection, temporal reasoning, and belief revision.
"""

from __future__ import annotations

from .contracts import (
    BeliefAssessment,
    BeliefClaim,
    BeliefContradiction,
    BeliefRevision,
    BeliefVerdict,
    ClaimComparison,
    ClaimStatus,
    ClaimTemporalValidity,
    ClaimScope,
    ConfidenceMetrics,
    ContradictionKind,
    ContradictionNature,
    ConfidenceDimension,
    UncertaintySource,
    Evidence,
    EvidenceRelation,
    EvidenceStrength,
    EvidenceType,
    RevisionAction,
    EVIDENCE_STRENGTH_WEIGHTS,
    SOURCE_CREDIBILITY,
    STALENESS_THRESHOLD_HOURS,
    make_claim_id,
    make_contradiction_id,
    make_evidence_id,
    make_revision_id,
)
from .assessment import BeliefEngine
from .contradiction import ContradictionDetector
from .temporal import TemporalReasoner
from .revision import BeliefRevisionEngine

__all__ = [
    "BeliefAssessment",
    "BeliefClaim",
    "BeliefContradiction",
    "BeliefEngine",
    "BeliefRevision",
    "BeliefRevisionEngine",
    "BeliefVerdict",
    "ClaimComparison",
    "ClaimStatus",
    "ClaimTemporalValidity",
    "ClaimScope",
    "ConfidenceDimension",
    "ConfidenceMetrics",
    "ContradictionDetector",
    "ContradictionKind",
    "ContradictionNature",
    "EVIDENCE_STRENGTH_WEIGHTS",
    "Evidence",
    "EvidenceRelation",
    "EvidenceStrength",
    "EvidenceType",
    "RevisionAction",
    "SOURCE_CREDIBILITY",
    "STALENESS_THRESHOLD_HOURS",
    "TemporalReasoner",
    "UncertaintySource",
    "make_claim_id",
    "make_contradiction_id",
    "make_evidence_id",
    "make_revision_id",
]
