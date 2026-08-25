"""Belief, uncertainty, evidence, and contradiction contracts.

Belief reasoning evaluates claims and evidence. Memory owns the canonical claim
lifecycle; this module imports that lifecycle rather than defining a competing
one. No persistence or provider execution belongs here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ai_karen_engine.core.memory.contracts import ClaimStatus
from ai_karen_engine.core.reasoning.contracts import ContradictionSeverity

ClaimId = str
EvidenceId = str


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class ConfidenceDimension(str, Enum):
    SOURCE = "source"
    EVIDENCE_STRENGTH = "evidence_strength"
    BELIEF = "belief"
    FRESHNESS = "freshness"
    CONSISTENCY = "consistency"


class UncertaintySource(str, Enum):
    NEW_CLAIM = "new_claim"
    CONTRADICTORY_EVIDENCE = "contradictory_evidence"
    STALE_EVIDENCE = "stale_evidence"
    LOW_SOURCE_CREDENCE = "low_source_credence"
    SCOPE_MISMATCH = "scope_mismatch"
    TEMPORAL_GAP = "temporal_gap"
    SINGLE_SOURCE = "single_source"
    INFERENCE_ONLY = "inference_only"


class EvidenceType(str, Enum):
    """Canonical evidence taxonomy for cognitive evidence."""

    USER_STATEMENT = "user_statement"
    OBSERVATION = "observation"
    TOOL_RESULT = "tool_result"
    MEMORY = "memory"
    DOCUMENT = "document"
    EXTERNAL_SOURCE = "external_source"
    SYSTEM_INFERENCE = "system_inference"
    OUTCOME = "outcome"


class EvidenceRelation(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies"
    SUPERSEDES = "supersedes"
    CORROBORATES = "corroborates"
    WEAKENS = "weakens"


class EvidenceStrength(str, Enum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    DEFINITIVE = "definitive"


class ClaimScope(str, Enum):
    GLOBAL = "global"
    USER = "user"
    TENANT = "tenant"
    CONVERSATION = "conversation"
    SESSION = "session"
    PROJECT = "project"


class ContradictionKind(str, Enum):
    DIRECT = "direct"
    TEMPORAL = "temporal"
    SCOPE = "scope"
    SOURCE_DISAGREEMENT = "source_disagreement"
    PREFERENCE_DRIFT = "preference_drift"
    IDENTITY_CONFLICT = "identity_conflict"
    GOAL_CONFLICT = "goal_conflict"


class ContradictionNature(str, Enum):
    CONTRADICTION = "contradiction"
    CHANGE_OVER_TIME = "change_over_time"


class RevisionAction(str, Enum):
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
    ACTIVE = "active"
    INACTIVE = "inactive"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    STALE_EVIDENCE = "stale_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


@dataclass(slots=True)
class ClaimTemporalValidity:
    asserted_at: datetime | None = None
    observed_at: datetime | None = None
    event_time: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    last_verified_at: datetime | None = None
    superseded_at: datetime | None = None
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in (
            "asserted_at",
            "observed_at",
            "event_time",
            "valid_from",
            "valid_until",
            "last_verified_at",
            "superseded_at",
            "deleted_at",
        ):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                setattr(self, name, value.replace(tzinfo=timezone.utc))

    def is_expired(self, now: datetime | None = None) -> bool:
        check = now or utc_now()
        if check.tzinfo is None:
            check = check.replace(tzinfo=timezone.utc)
        return self.valid_until is not None and check > self.valid_until

    def age_seconds(self, now: datetime | None = None) -> float:
        check = now or utc_now()
        if check.tzinfo is None:
            check = check.replace(tzinfo=timezone.utc)
        reference = self.last_verified_at or self.observed_at or self.asserted_at
        if reference is None:
            return float("inf")
        return (check - reference).total_seconds()


@dataclass(slots=True)
class BeliefClaim:
    """Epistemic claim. A claim is never automatically a verified fact."""

    claim_id: str
    subject: str
    predicate: str
    object: str
    status: ClaimStatus
    source: EvidenceType
    source_ref: str | None
    scope: ClaimScope
    confidence: float
    tenant_id: str
    user_id: str | None
    claim_format: str
    provenance: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    temporal: ClaimTemporalValidity = field(default_factory=ClaimTemporalValidity)
    evidence_ids: list[EvidenceId] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    superseded_by: ClaimId | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("BeliefClaim requires an explicit tenant_id")
        self.confidence = max(0.0, min(1.0, self.confidence))


@dataclass(slots=True)
class Evidence:
    evidence_id: str
    type: EvidenceType
    source: str
    source_ref: str | None
    content: str
    summary: str = ""
    strength: EvidenceStrength = EvidenceStrength.MODERATE
    relation: EvidenceRelation = EvidenceRelation.SUPPORTS
    confidence: float = 0.0
    observed_at: datetime | None = None
    event_time: datetime | None = None
    expires_at: datetime | None = None
    authority: str = ""
    tenant_id: str = ""
    user_id: str | None = None
    claim_ids: list[ClaimId] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    sensitivity: str = "internal"
    redacted: bool = False

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("Evidence requires an explicit tenant_id")
        self.confidence = max(0.0, min(1.0, self.confidence))
        for name in ("observed_at", "event_time", "expires_at"):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                setattr(self, name, value.replace(tzinfo=timezone.utc))

    def redact(self) -> "Evidence":
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
            event_time=self.event_time,
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
    contradiction_id: str
    claim_a_id: str
    claim_b_id: str | None
    kind: ContradictionKind
    nature: ContradictionNature
    severity: ContradictionSeverity
    description: str
    evidence_refs: list[str] = field(default_factory=list)
    detected_at: datetime = field(default_factory=utc_now)
    tenant_id: str = ""
    resolved: bool = False
    resolution: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("BeliefContradiction requires an explicit tenant_id")


@dataclass(slots=True)
class ConfidenceMetrics:
    """Epistemic confidence dimensions. Not interchangeable with recall/salience."""

    source_confidence: float = 0.0
    evidence_strength: float = 0.0
    belief_confidence: float = 0.0
    freshness_confidence: float = 0.0
    consistency_confidence: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "source_confidence",
            "evidence_strength",
            "belief_confidence",
            "freshness_confidence",
            "consistency_confidence",
        ):
            setattr(self, name, max(0.0, min(1.0, getattr(self, name))))

    @property
    def overall(self) -> float:
        values = (
            self.source_confidence,
            self.evidence_strength,
            self.belief_confidence,
            self.freshness_confidence,
            self.consistency_confidence,
        )
        product = 1.0
        for value in values:
            product *= value
        return float(product ** (1.0 / len(values)))


@dataclass(slots=True)
class BeliefAssessment:
    claim_id: str
    status: ClaimStatus
    overall_confidence: float
    confidence_metrics: ConfidenceMetrics
    reason_codes: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    uncertainty_sources: list[UncertaintySource] = field(default_factory=list)
    contradictions: list[BeliefContradiction] = field(default_factory=list)
    verdict: BeliefVerdict = BeliefVerdict.ACTIVE

    def __post_init__(self) -> None:
        self.overall_confidence = max(0.0, min(1.0, self.overall_confidence))


@dataclass(slots=True)
class ClaimComparison:
    claim_a_id: str
    claim_b_id: str
    relationship: str
    confidence_a: float
    confidence_b: float
    assessment_a: BeliefAssessment | None = None
    assessment_b: BeliefAssessment | None = None
    evidence_overlap: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BeliefRevision:
    revision_id: str
    claim_id: str
    action: RevisionAction
    reason: str
    evidence_ref: str | None
    confidence_before: float
    confidence_after: float
    revised_at: datetime = field(default_factory=utc_now)
    tenant_id: str = ""
    superseded_claim_id: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("BeliefRevision requires an explicit tenant_id")


EVIDENCE_STRENGTH_WEIGHTS: dict[EvidenceStrength, float] = {
    EvidenceStrength.WEAK: 0.3,
    EvidenceStrength.MODERATE: 0.6,
    EvidenceStrength.STRONG: 0.85,
    EvidenceStrength.DEFINITIVE: 1.0,
}

SOURCE_CREDIBILITY: dict[EvidenceType, float] = {
    EvidenceType.USER_STATEMENT: 0.85,
    EvidenceType.OBSERVATION: 0.6,
    EvidenceType.TOOL_RESULT: 0.7,
    EvidenceType.MEMORY: 0.5,
    EvidenceType.DOCUMENT: 0.6,
    EvidenceType.EXTERNAL_SOURCE: 0.4,
    EvidenceType.SYSTEM_INFERENCE: 0.3,
    EvidenceType.OUTCOME: 0.75,
}

STALENESS_THRESHOLD_HOURS: float = 24.0 * 7


def make_claim_id() -> str:
    return f"claim_{uuid.uuid4().hex[:16]}"


def make_evidence_id() -> str:
    return f"ev_{uuid.uuid4().hex[:16]}"


def make_contradiction_id() -> str:
    return f"contra_{uuid.uuid4().hex[:16]}"


def make_revision_id() -> str:
    return f"rev_{uuid.uuid4().hex[:16]}"


__all__ = [
    "EVIDENCE_STRENGTH_WEIGHTS",
    "SOURCE_CREDIBILITY",
    "STALENESS_THRESHOLD_HOURS",
    "BeliefAssessment",
    "BeliefClaim",
    "BeliefContradiction",
    "BeliefRevision",
    "BeliefVerdict",
    "ClaimComparison",
    "ClaimId",
    "ClaimScope",
    "ClaimStatus",
    "ClaimTemporalValidity",
    "ConfidenceDimension",
    "ConfidenceMetrics",
    "ContradictionKind",
    "ContradictionNature",
    "ContradictionSeverity",
    "Evidence",
    "EvidenceId",
    "EvidenceRelation",
    "EvidenceStrength",
    "EvidenceType",
    "RevisionAction",
    "UncertaintySource",
    "make_claim_id",
    "make_contradiction_id",
    "make_evidence_id",
    "make_revision_id",
]
