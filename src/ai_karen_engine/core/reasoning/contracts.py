"""Canonical reasoning contracts for the specialist cognition layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

from ai_karen_engine.core.contracts.cognitive import ReasoningConfidence, ReasoningDepth
from ai_karen_engine.core.contracts.values import JsonMap


class ReasoningStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_EVIDENCE = "waiting_for_evidence"
    COMPLETED = "completed"
    ABSTAINED = "abstained"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReasoningMode(str, Enum):
    CAUSAL = "causal"
    COUNTERFACTUAL = "counterfactual"
    EVIDENCE_SYNTHESIS = "evidence_synthesis"
    HYPOTHESIS_COMPARISON = "hypothesis_comparison"
    VERIFICATION = "verification"
    REFINEMENT = "refinement"
    SOFT_EXPLORATION = "soft_exploration"
    METACOGNITION = "metacognition"


_REASONING_MODE_ALIASES = {
    "verify": ReasoningMode.VERIFICATION.value,
    "refine": ReasoningMode.REFINEMENT.value,
    "synthesis": ReasoningMode.EVIDENCE_SYNTHESIS.value,
    "soft": ReasoningMode.SOFT_EXPLORATION.value,
    # Compatibility shim for the legacy ChatRuntime call site. Remove when
    # ChatRuntime passes ExecutionDecision.reasoning_modes directly.
    "reasoning": ReasoningMode.EVIDENCE_SYNTHESIS.value,
}


class HypothesisStatus(str, Enum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    WEAK = "weak"
    CONTRADICTED = "contradicted"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"


class ContradictionSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EvidenceSensitivity(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    SECRET = "secret"


class ReasoningDisposition(str, Enum):
    COMPLETE = "complete"
    REQUEST_EVIDENCE = "request_evidence"
    ESCALATE = "escalate"
    ABSTAIN = "abstain"


class ReasoningErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    POLICY_CONTEXT_MISSING = "policy_context_missing"
    EVIDENCE_INVALID = "evidence_invalid"
    EVIDENCE_SCOPE_VIOLATION = "evidence_scope_violation"
    STRATEGY_UNAVAILABLE = "strategy_unavailable"
    STRATEGY_FAILURE = "strategy_failure"
    GENERATION_FAILURE = "generation_failure"
    OUTPUT_SCHEMA_INVALID = "output_schema_invalid"
    BUDGET_EXCEEDED = "budget_exceeded"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    CANCELLED = "cancelled"
    ESCALATION_DENIED = "escalation_denied"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_reasoning_modes(values: list[str]) -> list[str]:
    """Normalize known aliases and reject arbitrary capability leakage."""
    allowed = {mode.value for mode in ReasoningMode}
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip().lower()
        if not value:
            continue
        value = _REASONING_MODE_ALIASES.get(value, value)
        if value not in allowed:
            raise ValueError(f"unsupported reasoning mode: {raw}")
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized


@dataclass(slots=True)
class ReasoningEvidence:
    evidence_id: str
    type: str
    source: str
    source_ref: str
    content: str
    tenant_id: str
    summary: str = ""
    relevance: float = 0.0
    confidence: float = 0.0
    event_time: datetime | None = None
    observed_at: datetime | None = None
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    expires_at: datetime | None = None
    provenance: str = ""
    sensitivity: str = EvidenceSensitivity.INTERNAL.value
    authority: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("reasoning evidence requires explicit non-default tenant_id")
        self.relevance = max(0.0, min(1.0, self.relevance))
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.recorded_at = _utc(self.recorded_at)
        for name in ("event_time", "observed_at", "valid_from", "valid_until", "expires_at"):
            value = getattr(self, name)
            if value is not None:
                setattr(self, name, _utc(value))

    @property
    def timestamp(self) -> float:
        """Deprecated compatibility view; use recorded_at."""
        return self.recorded_at.timestamp()

    @property
    def valid_at(self) -> str | None:
        """Deprecated compatibility view; use valid_from."""
        return self.valid_from.isoformat() if self.valid_from else None


@dataclass(slots=True)
class ReasoningHypothesis:
    hypothesis_id: str
    statement: str
    confidence: float = 0.0
    supporting_evidence_refs: list[str] = field(default_factory=list)
    contradicting_evidence_refs: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    uncertainty: float = 0.0
    status: str = HypothesisStatus.PROPOSED.value
    provenance: str = ""


@dataclass(slots=True)
class ReasoningContradiction:
    claim_a: str
    claim_b: str
    evidence_refs: list[str] = field(default_factory=list)
    severity: str = ContradictionSeverity.MEDIUM.value
    resolvable: bool = True
    recommended_action: str = ""


@dataclass(slots=True)
class ReasoningAssessment:
    confidence: ReasoningConfidence = field(default_factory=ReasoningConfidence)
    evidence_sufficiency: float = 0.0
    contradiction_severity: str = ContradictionSeverity.LOW.value
    uncertainty_reasons: list[str] = field(default_factory=list)
    metrics: JsonMap = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.confidence, ReasoningConfidence):
            self.confidence = ReasoningConfidence(float(self.confidence))
        self.evidence_sufficiency = max(0.0, min(1.0, self.evidence_sufficiency))


@dataclass(slots=True)
class ReasoningEvidenceNeed:
    capability: str = ""
    description: str = ""
    query: str = ""
    priority: str = "medium"
    required: bool = True
    reason: str = ""


@dataclass(slots=True)
class ReasoningEscalationRequest:
    requested_topology: str | None = None
    reason: str = ""
    required_capabilities: list[str] = field(default_factory=list)
    required_budget_delta: JsonMap = field(default_factory=dict)
    evidence_needs: list[ReasoningEvidenceNeed] = field(default_factory=list)


@dataclass(slots=True)
class ReasoningAction:
    action_type: str
    description: str = ""
    parameters: JsonMap = field(default_factory=dict)


@dataclass(slots=True)
class ReasoningBudget:
    max_reasoning_steps: int = 5
    max_model_calls: int = 3
    max_tool_requests: int = 2
    max_refinement_iterations: int = 2
    max_duration_ms: int = 20000
    max_input_tokens: int = 8192
    max_output_tokens: int = 4096


@dataclass(slots=True)
class ReasoningRequest:
    request_id: str
    correlation_id: str
    tenant_id: str
    user_id: str
    conversation_id: str | None
    objective: str
    reasoning_modes: list[str]
    evidence: list[ReasoningEvidence]
    constraints: JsonMap
    policy_decision_id: str
    budget: ReasoningBudget
    metadata: dict[str, Any]
    schema_version: str = "v1"

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("reasoning request requires explicit non-default tenant_id")
        if not self.objective.strip():
            raise ValueError("reasoning request requires a non-empty objective")
        self.reasoning_modes = normalize_reasoning_modes(self.reasoning_modes)


@dataclass(slots=True)
class ReasoningResult:
    reasoning_id: str
    disposition: str
    conclusion: str
    hypotheses: list[ReasoningHypothesis]
    evidence: list[ReasoningEvidence]
    assumptions: list[str]
    unknowns: list[str]
    contradictions: list[ReasoningContradiction]
    assessment: ReasoningAssessment
    evidence_needs: list[ReasoningEvidenceNeed]
    suggested_next_actions: list[ReasoningAction]
    status: str
    error_code: str | None = None
    escalation: ReasoningEscalationRequest | None = None
    memory_candidates: list[JsonMap] = field(default_factory=list)
    trajectory_ref: str | None = None
    diagnostics: JsonMap = field(default_factory=dict)
    schema_version: str = "v1"

    @property
    def summary(self) -> str:
        """Deprecated compatibility view for pre-convergence runtime callers."""
        return self.conclusion


class EvidenceProvider(Protocol):
    async def retrieve(self, request: ReasoningRequest, context: Any) -> list[ReasoningEvidence]: ...


class ReasoningGenerationClient(Protocol):
    async def generate(self, request: Any) -> Any: ...


class ReasoningToolClient(Protocol):
    async def execute(self, capability: str, query: str, context: Any) -> JsonMap: ...


__all__ = [
    "ContradictionSeverity",
    "EvidenceProvider",
    "EvidenceSensitivity",
    "HypothesisStatus",
    "ReasoningAction",
    "ReasoningAssessment",
    "ReasoningBudget",
    "ReasoningContradiction",
    "ReasoningDepth",
    "ReasoningDisposition",
    "ReasoningErrorCode",
    "ReasoningEscalationRequest",
    "ReasoningEvidence",
    "ReasoningEvidenceNeed",
    "ReasoningGenerationClient",
    "ReasoningHypothesis",
    "ReasoningMode",
    "ReasoningRequest",
    "ReasoningResult",
    "ReasoningStatus",
    "ReasoningToolClient",
    "normalize_reasoning_modes",
]
