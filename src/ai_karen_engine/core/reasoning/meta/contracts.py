from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MetaCognitiveDimension(str, Enum):
    KNOWLEDGE_SUFFICIENCY = "knowledge_sufficiency"
    MEMORY_RELIABILITY = "memory_reliability"
    EVIDENCE_CONSISTENCY = "evidence_consistency"
    REASONING_CONFIDENCE = "reasoning_confidence"
    STRATEGY_CONFIDENCE = "strategy_confidence"
    CONTEXT_COMPLETENESS = "context_completeness"
    VERIFICATION_NEED = "verification_need"
    AMBIGUITY = "ambiguity"
    RISK_AWARENESS = "risk_awareness"


class MetaStatus(str, Enum):
    STABLE = "stable"
    UNCERTAIN = "uncertain"
    CONFLICTED = "conflicted"
    INSUFFICIENT = "insufficient"
    STALE = "stale"
    DEGRADED = "degraded"
    LOOPING = "looping"
    VERIFICATION_REQUIRED = "verification_required"
    HUMAN_INPUT_REQUIRED = "human_input_required"


class MetaReasonCode(str, Enum):
    LOW_MEMORY_CONFIDENCE = "low_memory_confidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    STALE_MEMORY = "stale_memory"
    HIGH_RISK_UNCERTAIN_CLAIM = "high_risk_uncertain_claim"
    REPEATED_FAILED_STRATEGY = "repeated_failed_strategy"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    LOOP_DETECTED = "loop_detected"
    MARGINAL_GAIN = "marginal_gain"
    BUDGET_EXHAUSTED = "budget_exhausted"
    EVIDENCE_SUFFICIENT = "evidence_sufficient"
    STRATEGY_EXHAUSTED = "strategy_exhausted"


class ReasoningDepth(str, Enum):
    NONE = "none"
    LIGHT = "light"
    STANDARD = "standard"
    DEEP = "deep"


class LoopDetectionStrategy(str, Enum):
    SAME_STRATEGY = "same_strategy"
    SAME_EVIDENCE = "same_evidence"
    SAME_FAILED_OUTCOME = "same_failed_outcome"


@dataclass(slots=True)
class MetaCognitiveState:
    """Multi-dimensional meta-cognitive state."""
    knowledge_sufficiency: float = 0.0
    memory_reliability: float = 0.0
    evidence_consistency: float = 0.0
    reasoning_confidence: float = 0.0
    strategy_confidence: float = 0.0
    context_completeness: float = 0.0
    verification_need: float = 0.0
    ambiguity: float = 0.0
    risk_awareness: float = 0.0
    confidence: float = 0.0
    reason_codes: list[MetaReasonCode] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MetaAssessment:
    """Assessment of cognitive quality."""
    status: MetaStatus = MetaStatus.STABLE
    confidence: float = 0.0
    issues: list[str] = field(default_factory=list)
    recommended_cognitive_actions: list[str] = field(default_factory=list)
    reason_codes: list[MetaReasonCode] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    assessed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(slots=True)
class StrategyAttempt:
    """Record of a reasoning strategy attempt."""
    strategy_id: str
    strategy_type: str
    evidence_hashes: list[str] = field(default_factory=list)
    outcome: str = "unknown"
    confidence: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StrategyFingerprint:
    """Fingerprint for loop detection."""
    strategy_type: str
    evidence_hash: str
    outcome_class: str


@dataclass(slots=True)
class LoopAssessment:
    """Assessment of reasoning loop state."""
    is_looping: bool = False
    loop_count: int = 0
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    fingerprint: StrategyFingerprint | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BeliefConflictSummary:
    """Summary of evidence conflicts for meta-cognition."""
    conflict_id: str
    claim_a: str
    claim_b: str
    severity: str = "medium"
    resolvable: bool = True
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryReliabilityAssessment:
    """Assessment of memory reliability."""
    recall_confidence: float = 0.0
    memory_age: str = "unknown"
    contradiction_count: int = 0
    source_diversity: float = 0.0
    retrieval_degradation: float = 0.0
    reliability: float = 0.0
    reason_codes: list[MetaReasonCode] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VerificationNeedAssessment:
    """Assessment of verification need."""
    required: bool = False
    reason: MetaReasonCode | None = None
    depth: ReasoningDepth = ReasoningDepth.STANDARD
    urgency: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReasoningDepthRecommendation:
    """Recommendation for reasoning depth."""
    recommended_depth: ReasoningDepth = ReasoningDepth.STANDARD
    reason: MetaReasonCode | None = None
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CalibrationObservation:
    """Observation for calibration tracking."""
    predicted_confidence: float = 0.0
    actual_outcome: str = "unknown"
    correction_required: bool = False
    verification_result: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MetaCognitiveRequest:
    """Request for meta-cognitive assessment."""
    request_id: str
    correlation_id: str
    tenant_id: str = "default"
    reasoning_confidence: float = 0.0
    memory_reliability: float = 0.0
    evidence_consistency: float = 0.0
    strategy_attempts: list[StrategyAttempt] = field(default_factory=list)
    belief_conflicts: list[BeliefConflictSummary] = field(default_factory=list)
    budget_remaining: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MetaCognitiveResult:
    """Result of meta-cognitive assessment."""
    assessment: MetaAssessment
    state: MetaCognitiveState
    loop_assessment: LoopAssessment | None = None
    memory_reliability: MemoryReliabilityAssessment | None = None
    verification_need: VerificationNeedAssessment | None = None
    depth_recommendation: ReasoningDepthRecommendation | None = None
    calibration_observations: list[CalibrationObservation] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    assessed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
