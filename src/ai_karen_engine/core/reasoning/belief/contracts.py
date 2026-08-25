"""Belief / uncertainty / contradiction contracts for AI-Karen reasoning.

Belief owns epistemic assessment. Memory owns the canonical claim lifecycle.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ai_karen_engine.core.contracts.cognitive import EpistemicConfidence
from ai_karen_engine.core.memory.contracts import ClaimStatus

ClaimId = str
EvidenceId = str


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


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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

    def is_expired(self, now: datetime | None = None) -> bool:
        current = _utc(now or datetime.now(timezone.utc))
        return self.valid_until is not None and current > _utc(self.valid_until)

    def age_seconds(self, now: datetime | None = None) -> float:
        current = _utc(now or datetime.now(timezone.utc))
        ref = self.last_verified_at or self.observed_at or self.asserted_at
        if ref is None:
            return float("inf")
        return (current - _utc(ref)).total_seconds()


@dataclass(slots=True)
class BeliefClaim:
    claim_id: str
    subject: str
    predicate: str
    object: str
    status: ClaimStatus
    source: EvidenceType
    source_ref: str | None
    scope: ClaimScope
    confidence: EpistemicConfidence
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
            raise ValueError("belief tenant_id must be explicit and non-default")
        if not isinstance(self.confidence, EpistemicConfidence):
            self.confidence = EpistemicConfidence(float(self.confidence))


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
    tenant_id: str | None = None
    user_id: str | None = None
    claim_ids: list[ClaimId] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    sensitivity: str = "internal"
    redacted: bool = False

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence))
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("evidence tenant_id must be explicit and non-default")

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
    severity: str
    description: str
    evidence_refs: list[str] = field(default_factory=list)
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tenant_id: str | None = None
    resolved: bool = False
    resolution: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("contradiction tenant_id must be explicit and non-default")


@dataclass(slots=True)
class ConfidenceMetrics:
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
    def overall(self) -> EpistemicConfidence:
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
        return EpistemicConfidence(product ** (1.0 / len(values)))


@dataclass(slots=True)
class BeliefAssessment:
    claim_id: str
    status: ClaimStatus
    overall_confidence: EpistemicConfidence
    confidence_metrics: ConfidenceMetrics
    reason_codes: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    uncertainty_sources: list[UncertaintySource] = field(default_factory=list)
    contradictions: list[BeliefContradiction] = field(default_factory=list)
    verdict: BeliefVerdict = BeliefVerdict.ACTIVE


@dataclass(slots=True)
class ClaimComparison:
    claim_a_id: str
    claim_b_id: str
    relationship: str
    confidence_a: EpistemicConfidence
    confidence_b: EpistemicConfidence
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
    confidence_before: EpistemicConfidence
    confidence_after: EpistemicConfidence
    revised_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tenant_id: str | None = None
    superseded_claim_id: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("belief revision tenant_id must be explicit and non-default")


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
