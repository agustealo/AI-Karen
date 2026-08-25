"""Canonical reasoning contracts for the specialist cognition layer.

Reasoning consumes semantic evidence and produces typed reasoning artifacts. It
must not select providers, own runtime routing, or import persistence/platform
implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

from ai_karen_engine.core.contracts.cognitive import ReasoningDepth


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


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
    provenance: str = ""
    sensitivity: str = EvidenceSensitivity.INTERNAL.value
    event_time: datetime | None = None
    observed_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    authority: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    # Compatibility alias. Keep as datetime only; remove after legacy callers migrate.
    timestamp: datetime | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("ReasoningEvidence requires an explicit tenant_id")
        self.relevance = max(0.0, min(1.0, self.relevance))
        self.confidence = max(0.0, min(1.0, self.confidence))
        for name in (
            "event_time",
            "observed_at",
            "created_at",
            "valid_from",
            "valid_until",
            "timestamp",
        ):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                setattr(self, name, value.replace(tzinfo=timezone.utc))


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
    severity: ContradictionSeverity = ContradictionSeverity.MEDIUM
    resolvable: bool = True
    recommended_action: str = ""


@dataclass(slots=True)
class ReasoningAssessment:
    """Reasoning confidence, distinct from recall or epistemic confidence."""

    confidence: float = 0.0
    evidence_sufficiency: float = 0.0
    contradiction_severity: ContradictionSeverity = ContradictionSeverity.LOW
    uncertainty_reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence))
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
    required_budget_delta: dict[str, Any] = field(default_factory=dict)
    evidence_needs: list[ReasoningEvidenceNeed] = field(default_factory=list)


@dataclass(slots=True)
class ReasoningAction:
    action_type: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)


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
    constraints: dict[str, Any]
    policy_decision_id: str
    budget: ReasoningBudget
    metadata: dict[str, Any]
    reasoning_depth: ReasoningDepth = ReasoningDepth.STANDARD
    schema_version: str = "v2"
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("ReasoningRequest requires an explicit tenant_id")


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
    memory_candidates: list[dict[str, Any]] = field(default_factory=list)
    trajectory_ref: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "v2"
    created_at: datetime = field(default_factory=utc_now)


class EvidenceProvider(Protocol):
    async def retrieve(
        self,
        request: ReasoningRequest,
        context: Any,
    ) -> list[ReasoningEvidence]: ...


class ReasoningGenerationClient(Protocol):
    async def generate(self, request: Any) -> Any: ...


class ReasoningToolClient(Protocol):
    async def execute(
        self,
        capability: str,
        query: str,
        context: Any,
    ) -> dict[str, Any]: ...


__all__ = [
    "ContradictionSeverity",
    "EvidenceProvider",
    "EvidenceSensitivity",
    "HypothesisStatus",
    "ReasoningAction",
    "ReasoningAssessment",
    "ReasoningBudget",
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
]
