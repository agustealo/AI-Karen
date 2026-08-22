"""Canonical reasoning contracts for the specialist cognition layer.

These dataclasses are the single source of truth for all reasoning artifacts.
No reasoning strategy, executor, or node should invent its own dictionary shape
when these contracts exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Tuple


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


# ===================================
# Evidence
# ===================================

@dataclass(slots=True)
class ReasoningEvidence:
    evidence_id: str
    type: str
    source: str
    source_ref: str
    content: str
    summary: str = ""
    relevance: float = 0.0
    confidence: float = 0.0
    timestamp: float = 0.0
    provenance: str = ""
    tenant_id: str = "default"
    sensitivity: str = EvidenceSensitivity.INTERNAL.value
    valid_at: Optional[str] = None
    observed_at: Optional[str] = None
    recorded_at: Optional[str] = None
    expires_at: Optional[str] = None
    authority: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ===================================
# Hypothesis
# ===================================

@dataclass(slots=True)
class ReasoningHypothesis:
    hypothesis_id: str
    statement: str
    confidence: float = 0.0
    supporting_evidence_refs: List[str] = field(default_factory=list)
    contradicting_evidence_refs: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    uncertainty: float = 0.0
    status: str = HypothesisStatus.PROPOSED.value
    provenance: str = ""


# ===================================
# Contradiction
# ===================================

@dataclass(slots=True)
class ReasoningContradiction:
    claim_a: str
    claim_b: str
    evidence_refs: List[str] = field(default_factory=list)
    severity: str = ContradictionSeverity.MEDIUM.value
    resolvable: bool = True
    recommended_action: str = ""


# ===================================
# Assessment (simplified confidence)
# ===================================

@dataclass(slots=True)
class ReasoningAssessment:
    confidence: float = 0.0
    evidence_sufficiency: float = 0.0
    contradiction_severity: str = ContradictionSeverity.LOW.value
    uncertainty_reasons: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)


# ===================================
# Evidence need / escalation
# ===================================

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
    requested_topology: Optional[str] = None
    reason: str = ""
    required_capabilities: List[str] = field(default_factory=list)
    required_budget_delta: Dict[str, Any] = field(default_factory=dict)
    evidence_needs: List[ReasoningEvidenceNeed] = field(default_factory=list)


# ===================================
# Action
# ===================================

@dataclass(slots=True)
class ReasoningAction:
    action_type: str
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)


# ===================================
# Budget
# ===================================

@dataclass(slots=True)
class ReasoningBudget:
    max_reasoning_steps: int = 5
    max_model_calls: int = 3
    max_tool_requests: int = 2
    max_refinement_iterations: int = 2
    max_duration_ms: int = 20000
    max_input_tokens: int = 8192
    max_output_tokens: int = 4096


# ===================================
# Canonical Request / Result
# ===================================

@dataclass(slots=True)
class ReasoningRequest:
    request_id: str
    correlation_id: str
    tenant_id: str
    user_id: str
    conversation_id: Optional[str]
    objective: str
    reasoning_modes: List[str]
    evidence: List[ReasoningEvidence]
    constraints: Dict[str, Any]
    policy_decision_id: str
    budget: ReasoningBudget
    metadata: Dict[str, Any]
    schema_version: str = "v1"


@dataclass(slots=True)
class ReasoningResult:
    reasoning_id: str
    disposition: str
    conclusion: str
    hypotheses: List[ReasoningHypothesis]
    evidence: List[ReasoningEvidence]
    assumptions: List[str]
    unknowns: List[str]
    contradictions: List[ReasoningContradiction]
    assessment: ReasoningAssessment
    evidence_needs: List[ReasoningEvidenceNeed]
    suggested_next_actions: List[ReasoningAction]
    status: str
    error_code: Optional[str] = None
    escalation: Optional[ReasoningEscalationRequest] = None
    memory_candidates: List[Dict[str, Any]] = field(default_factory=list)
    trajectory_ref: Optional[str] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = "v1"


# ===================================
# Protocols
# ===================================

class EvidenceProvider(Protocol):
    async def retrieve(
        self,
        request: ReasoningRequest,
        context: Any,
    ) -> List[ReasoningEvidence]:
        ...


class ReasoningGenerationClient(Protocol):
    async def generate(self, request: Any) -> Any:
        ...


class ReasoningToolClient(Protocol):
    async def execute(self, capability: str, query: str, context: Any) -> Dict[str, Any]:
        ...
