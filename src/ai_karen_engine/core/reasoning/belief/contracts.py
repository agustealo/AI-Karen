"""
Belief / Uncertainty / Contradiction contracts for AI-Karen reasoning.

Gives Karen a first-class way to distinguish what she observed, what the user
asserted, what she inferred, what she verified, what she suspects, what is
contradicted, what used to be true, and what is unknown.

These are domain contracts, NOT persistence or provider calls.
Belief logic evaluates evidence; memory stores it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


# ===================================
# TYPE ALIASES
# ===================================

ClaimId = str
EvidenceId = str


# ===================================
# CLAIM STATUS
# ===================================

class ClaimStatus(str, Enum):
    """Status of a belief claim through its epistemic lifecycle."""
    OBSERVED = "observed"
    USER_ASSERTED = "user_asserted"
    INFERRED = "inferred"
    SUPPORTED = "supported"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    CONTRADICTED = "contradicted"
    SUPERSEDED = "superseded"
    STALE = "stale"
    RETRACTED = "retracted"
    UNKNOWN = "unknown"


class ConfidenceDimension(str, Enum):
    """Dimensions of confidence for a claim."""
    SOURCE = "source"
    EVIDENCE_STRENGTH = "evidence_strength"
    BELIEF = "belief"
    FRESHNESS = "freshness"
    CONSISTENCY = "consistency"


class UncertaintySource(str, Enum):
    """What contributes to uncertainty about a claim."""
    NEW_CLAIM = "new_claim"
    CONTRADICTORY_EVIDENCE = "contradictory_evidence"
    STALE_EVIDENCE = "stale_evidence"
    LOW_SOURCE_CREDENCE = "low_source_credence"
    SCOPE_MISMATCH = "scope_mismatch"
    TEMPORAL_GAP = "temporal_gap"
    SINGLE_SOURCE = "single_source"
    INFERENCE_ONLY = "inference_only"


class EvidenceType(str, Enum):
    """Type of evidence supporting or contradicting a claim."""
    USER_STATEMENT = "user_statement"
    OBSERVATION = "observation"
    TOOL_RESULT = "tool_result"
    MEMORY = "memory"
    DOCUMENT = "document"
    EXTERNAL_SOURCE = "external_source"
    SYSTEM_INFERENCE = "system_inference"
    OUTCOME = "outcome"


class EvidenceRelation(str, Enum):
    """How an evidence item relates to a claim."""
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies"
    SUPERSEDES = "supersedes"
    CORROBORATES = "corroborates"
    WEAKENS = "weakens"


class EvidenceStrength(str, Enum):
    """Strength of an evidence item."""
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    DEFINITIVE = "definitive"


class ClaimScope(str, Enum):
    """Scope of applicability for a claim."""
    GLOBAL = "global"
    USER = "user"
    TENANT = "tenant"
    CONVERSATION = "conversation"
    SESSION = "session"
    PROJECT = "project"


class ContradictionKind(str, Enum):
    """Kind of contradiction detected between claims."""
    DIRECT = "direct"
    TEMPORAL = "temporal"
    SCOPE = "scope"
    SOURCE_DISAGREEMENT = "source_disagreement"
    PREFERENCE_DRIFT = "preference_drift"
    IDENTITY_CONFLICT = "identity_conflict"
    GOAL_CONFLICT = "goal_conflict"


class ContradictionNature(str, Enum):
    """Whether a contradiction is a true contradiction or a change over time."""
    CONTRADICTION = "contradiction"
    CHANGE_OVER_TIME = "change_over_time"


class RevisionAction(str, Enum):
    """Action taken during belief revision."""
    KEEP = "keep"
    STRENGTHEN = "strengthen"
    WEAKEN = "weaken"
    MERGE = "merge"
    SUPERSEDE = "supersede"
    DISPUTE = "dispute"
    RETRACT = "retract"
    DEFER = "defer"
    VERIFY = "verify"


class BeliefVerdict(str, Enum):
    """Final verdict on a belief assessment."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    STALE_EVIDENCE = "stale_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


# ===================================
# CLAIM CONTRACTS
# ===================================

@dataclass(slots=True)
class ClaimTemporalValidity:
    """Temporal information for a claim."""
    asserted_at: Optional[datetime] = None
    observed_at: Optional[datetime] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    last_verified_at: Optional[datetime] = None

    @property
    def is_expired(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.utcnow()
        if self.valid_until is not None and now > self.valid_until:
            return True
        return False

    @property
    def age_seconds(self, now: Optional[datetime] = None) -> float:
        now = now or datetime.utcnow()
        ref = self.last_verified_at or self.observed_at or self.asserted_at
        if ref is None:
            return float("inf")
        return (now - ref).total_seconds()


@dataclass(slots=True)
class BeliefClaim:
    """A claim that Karen believes (or suspects) to be true.

    A claim is not automatically a fact.  It carries its epistemic provenance
    so that downstream consumers can reason about confidence.
    """
    claim_id: str
    subject: str
    predicate: str
    object: str
    status: ClaimStatus
    source: EvidenceType
    source_ref: Optional[str]
    scope: ClaimScope
    confidence: float
    tenant_id: str
    user_id: Optional[str]
    claim_format: str  # "triple" | "text" | "structured"
    provenance: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    temporal: ClaimTemporalValidity = field(default_factory=ClaimTemporalValidity)
    evidence_ids: List[EvidenceId] = field(default_factory=list)
    contradictions: List[str] = field(default_factory=list)
    superseded_by: Optional[ClaimId] = None
    version: int = 1

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence))


@dataclass(slots=True)
class Evidence:
    """A piece of evidence supporting or contradicting a claim."""
    evidence_id: str
    type: EvidenceType
    source: str
    source_ref: str
    content: str
    summary: str = ""
    strength: EvidenceStrength = EvidenceStrength.MODERATE
    relation: EvidenceRelation = EvidenceRelation.SUPPORTS
    confidence: float = 0.0
    observed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    authority: str = ""
    tenant_id: str = ""
    user_id: Optional[str] = None
    claim_ids: List[ClaimId] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    sensitivity: str = "internal"
    redacted: bool = False

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence))

    def redact(self) -> Evidence:
        """Return a redacted copy that strips secrets."""
        return Evidence(
            evidence_id=self.evidence_id,
            type=self.type,
            source=self.source,
            source_ref=None,
            content="[REDACTED]",
            summary=self.summary,
            strength=self.strength,
            relation=self.relation,
            confidence=self.confidence,
            observed_at=self.observed_at,
            expires_at=self.expires_at,
            authority=self.authority,
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            claim_ids=list(self.claim_ids),
            metadata={},
            sensitivity=self.sensitivity,
            redacted=True,
        )


@dataclass(slots=True)
class BeliefContradiction:
    """Records a contradiction between two claims or evidence items."""
    contradiction_id: str
    claim_a_id: str
    claim_b_id: Optional[str]
    kind: ContradictionKind
    nature: ContradictionNature
    severity: str
    description: str
    evidence_refs: List[str] = field(default_factory=list)
    detected_at: datetime = field(default_factory=datetime.utcnow)
    tenant_id: str = ""
    resolved: bool = False
    resolution: Optional[str] = None


@dataclass(slots=True)
class ConfidenceMetrics:
    """Multi-dimensional confidence for a claim."""
    source_confidence: float = 0.0
    evidence_strength: float = 0.0
    belief_confidence: float = 0.0
    freshness_confidence: float = 0.0
    consistency_confidence: float = 0.0

    def __post_init__(self) -> None:
        self.source_confidence = max(0.0, min(1.0, self.source_confidence))
        self.evidence_strength = max(0.0, min(1.0, self.evidence_strength))
        self.belief_confidence = max(0.0, min(1.0, self.belief_confidence))
        self.freshness_confidence = max(0.0, min(1.0, self.freshness_confidence))
        self.consistency_confidence = max(0.0, min(1.0, self.consistency_confidence))

    @property
    def overall(self) -> float:
        """Geometric-mean-style overall confidence."""
        values = [
            self.source_confidence,
            self.evidence_strength,
            self.belief_confidence,
            self.freshness_confidence,
            self.consistency_confidence,
        ]
        product = 1.0
        for v in values:
            product *= v
        return float(product ** (1.0 / len(values)))


@dataclass(slots=True)
class BeliefAssessment:
    """Result of assessing a claim with its evidence."""
    claim_id: str
    status: ClaimStatus
    overall_confidence: float
    confidence_metrics: ConfidenceMetrics
    reason_codes: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    uncertainty_sources: List[UncertaintySource] = field(default_factory=list)
    contradictions: List[BeliefContradiction] = field(default_factory=list)
    verdict: BeliefVerdict = BeliefVerdict.ACTIVE

    def __post_init__(self) -> None:
        self.overall_confidence = max(0.0, min(1.0, self.overall_confidence))


@dataclass(slots=True)
class ClaimComparison:
    """Comparison between two claims."""
    claim_a_id: str
    claim_b_id: str
    relationship: str  # "same", "contradictory", "corroborating", "independent"
    confidence_a: float
    confidence_b: float
    assessment_a: Optional[BeliefAssessment] = None
    assessment_b: Optional[BeliefAssessment] = None
    evidence_overlap: List[str] = field(default_factory=list)


@dataclass(slots=True)
class BeliefRevision:
    """Record of a belief revision action."""
    revision_id: str
    claim_id: str
    action: RevisionAction
    reason: str
    evidence_ref: Optional[str]
    confidence_before: float
    confidence_after: float
    revised_at: datetime = field(default_factory=datetime.utcnow)
    tenant_id: str = ""
    superseded_claim_id: Optional[str] = None


# ===================================
# EVIDENCE WEIGHTS
# ===================================

EVIDENCE_STRENGTH_WEIGHTS: Dict[EvidenceStrength, float] = {
    EvidenceStrength.WEAK: 0.3,
    EvidenceStrength.MODERATE: 0.6,
    EvidenceStrength.STRONG: 0.85,
    EvidenceStrength.DEFINITIVE: 1.0,
}

SOURCE_CREDIBILITY: Dict[EvidenceType, float] = {
    EvidenceType.USER_STATEMENT: 0.85,
    EvidenceType.OBSERVATION: 0.6,
    EvidenceType.TOOL_RESULT: 0.7,
    EvidenceType.MEMORY: 0.5,
    EvidenceType.DOCUMENT: 0.6,
    EvidenceType.EXTERNAL_SOURCE: 0.4,
    EvidenceType.SYSTEM_INFERENCE: 0.3,
    EvidenceType.OUTCOME: 0.75,
}

STALENESS_THRESHOLD_HOURS: float = 24.0 * 7  # 7 days


# ===================================
# ID HELPERS
# ===================================

def make_claim_id() -> str:
    return f"claim_{uuid.uuid4().hex[:16]}"


def make_evidence_id() -> str:
    return f"ev_{uuid.uuid4().hex[:16]}"


def make_contradiction_id() -> str:
    return f"contra_{uuid.uuid4().hex[:16]}"


def make_revision_id() -> str:
    return f"rev_{uuid.uuid4().hex[:16]}"


__all__ = [
    "ClaimId",
    "EvidenceId",
    "ClaimStatus",
    "ConfidenceDimension",
    "UncertaintySource",
    "EvidenceType",
    "EvidenceRelation",
    "EvidenceStrength",
    "ClaimScope",
    "ContradictionKind",
    "ContradictionNature",
    "RevisionAction",
    "BeliefVerdict",
    "ClaimTemporalValidity",
    "BeliefClaim",
    "Evidence",
    "BeliefContradiction",
    "ConfidenceMetrics",
    "BeliefAssessment",
    "ClaimComparison",
    "BeliefRevision",
    "EVIDENCE_STRENGTH_WEIGHTS",
    "SOURCE_CREDIBILITY",
    "STALENESS_THRESHOLD_HOURS",
    "make_claim_id",
    "make_evidence_id",
    "make_contradiction_id",
    "make_revision_id",
]
