from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

from ai_karen_engine.core.contracts.cognitive import ReasoningDepth
from ai_karen_engine.core.reasoning.contracts import (
    ReasoningAction,
    ReasoningAssessment,
    ReasoningBudget,
    ReasoningContradiction,
    ReasoningDisposition,
    ReasoningEvidence,
    ReasoningEvidenceNeed,
    ReasoningEscalationRequest,
    ReasoningErrorCode,
    ReasoningHypothesis,
    ReasoningRequest as CanonicalReasoningRequest,
    ReasoningResult as CanonicalReasoningResult,
    ReasoningStatus,
)


class RouteFamily(str, Enum):
    CHAT = "chat"
    SEARCH = "search"
    MEMORY = "memory"
    TOOL = "tool"
    AGENT = "agent"
    REASONING = "reasoning"
    ADMIN = "admin"
    DEGRADED = "degraded"


class ExecutionMode(str, Enum):
    DIRECT = "direct"
    LANGGRAPH = "langgraph"
    DEGRADED = "degraded"


@dataclass(slots=True)
class IntentSignal:
    primary_intent: str
    subtype: Optional[str] = None
    secondary_intents: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    confidence: float = 0.0
    category: str = "general"
    requested_modality: str = "text"
    requires_chat_capable_model: bool = True


@dataclass(slots=True)
class PredictorSignal:
    ambiguity_score: float = 0.0
    complexity_score: float = 0.0
    tool_likelihood: float = 0.0
    memory_relevance: float = 0.0
    multi_step_likelihood: float = 0.0
    degraded_risk: float = 0.0


@dataclass(slots=True)
class KireSignal:
    requires_reasoning: bool
    reasoning_depth: ReasoningDepth
    reasoning_modes: List[str] = field(default_factory=list)
    strategy_hint: Optional[str] = None
    should_use_memory: bool = True
    should_use_tools: bool = False
    should_use_retrieval_reasoning: bool = False
    should_use_causal_reasoning: bool = False
    should_use_graph_reasoning: bool = False
    should_self_refine: bool = False
    should_verify: bool = False


@dataclass(slots=True)
class RoutingDecision:
    route_family: RouteFamily
    execution_mode: ExecutionMode
    target_graph: str = "default_chat_graph"
    target_service: Optional[str] = None
    target_plugin: Optional[str] = None
    target_agent: Optional[str] = None
    allow_reasoning: bool = False
    allow_tools: bool = False
    allow_memory_read: bool = True
    allow_memory_write: bool = True
    require_approval_gate: bool = False


@dataclass(slots=True)
class UserContext:
    user_id: str
    tenant_id: str
    roles: List[str] = field(default_factory=list)
    session_id: Optional[str] = None
    thread_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("UserContext requires an explicit tenant_id")


@dataclass(slots=True)
class RuntimeRequest:
    message: str
    user: UserContext
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CortexOutput:
    intent: IntentSignal
    predictors: PredictorSignal
    kire: KireSignal
    routing: RoutingDecision
    correlation_id: str
    audit_tags: List[str] = field(default_factory=list)


@dataclass(slots=True)
class OrchestrationInput:
    message: str
    user: UserContext
    metadata: Dict[str, Any]
    cortex: CortexOutput


@dataclass(slots=True)
class ReasoningRequest:
    """Compatibility request used by legacy CORTEX reasoning callers.

    New integrations should prefer core.reasoning.contracts.ReasoningRequest.
    Sunset: remove after legacy CORTEX reasoning callers migrate.
    """

    message: str
    user: UserContext
    memory_context: Dict[str, Any]
    tool_context: Dict[str, Any]
    intent: IntentSignal
    predictors: PredictorSignal
    kire: KireSignal
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_canonical(self) -> CanonicalReasoningRequest:
        evidence: List[ReasoningEvidence] = []
        recall = (self.memory_context or {}).get("recall") or []
        for idx, item in enumerate(recall):
            if isinstance(item, dict):
                evidence.append(
                    ReasoningEvidence(
                        evidence_id=str(item.get("id", f"mem-{idx}")),
                        type="memory",
                        source="memory_recall",
                        source_ref=str(item.get("timestamp", "")),
                        content=str(item.get("content", "")),
                        relevance=0.5,
                        confidence=0.5,
                        tenant_id=self.user.tenant_id,
                    )
                )

        return CanonicalReasoningRequest(
            request_id=self.metadata.get("correlation_id", ""),
            correlation_id=self.metadata.get("correlation_id", ""),
            tenant_id=self.user.tenant_id,
            user_id=self.user.user_id,
            conversation_id=self.user.thread_id,
            objective=self.message,
            reasoning_modes=list(self.kire.reasoning_modes or []),
            evidence=evidence,
            constraints={
                "reasoning_depth": self.kire.reasoning_depth.value,
                "should_self_refine": self.kire.should_self_refine,
                "should_verify": self.kire.should_verify,
                "should_use_causal": self.kire.should_use_causal_reasoning,
                "should_use_graph": self.kire.should_use_graph_reasoning,
                "should_use_retrieval": self.kire.should_use_retrieval_reasoning,
            },
            policy_decision_id=self.metadata.get("policy_decision_id", ""),
            budget=ReasoningBudget(),
            metadata=self.metadata,
        )

    @classmethod
    def from_canonical(cls, canonical: CanonicalReasoningRequest) -> "ReasoningRequest":
        try:
            depth = ReasoningDepth(canonical.constraints.get("reasoning_depth", "standard"))
        except ValueError:
            depth = ReasoningDepth.STANDARD

        return cls(
            message=canonical.objective,
            user=UserContext(
                user_id=canonical.user_id,
                tenant_id=canonical.tenant_id,
                session_id=None,
                thread_id=canonical.conversation_id,
            ),
            memory_context={},
            tool_context={},
            intent=IntentSignal(primary_intent="reasoning"),
            predictors=PredictorSignal(),
            kire=KireSignal(
                requires_reasoning=True,
                reasoning_depth=depth,
                reasoning_modes=list(canonical.reasoning_modes or []),
                should_use_memory=bool(canonical.evidence),
                should_use_tools=False,
                should_use_retrieval_reasoning=canonical.constraints.get("should_use_retrieval", False),
                should_use_causal_reasoning=canonical.constraints.get("should_use_causal", False),
                should_use_graph_reasoning=canonical.constraints.get("should_use_graph", False),
                should_self_refine=canonical.constraints.get("should_self_refine", False),
                should_verify=canonical.constraints.get("should_verify", False),
            ),
            metadata=canonical.metadata,
        )


@dataclass(slots=True)
class ReasoningResult:
    """Compatibility result for legacy CORTEX reasoning callers.

    Sunset: remove after all consumers use CanonicalReasoningResult.
    """

    summary: str
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    hypotheses: List[str] = field(default_factory=list)
    confidence: float = 0.0
    verification_notes: List[str] = field(default_factory=list)
    refined_answer: Optional[str] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    degraded: bool = False
    reasoning_type: str = "synthesis"
    memory_ids: List[str] = field(default_factory=list)
    graph_paths_used: List[str] = field(default_factory=list)
    contradictions_found: List[Dict[str, Any]] = field(default_factory=list)
    needs_human_confirmation: bool = False
    fallback_used: Optional[str] = None
    evidence_source_mix: Dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_canonical(cls, canonical: CanonicalReasoningResult) -> "ReasoningResult":
        hypotheses = [hypothesis.statement for hypothesis in (canonical.hypotheses or [])]
        evidence = [
            {
                "id": item.evidence_id,
                "type": item.type,
                "source": item.source,
                "source_ref": item.source_ref,
                "content": item.content,
                "relevance": item.relevance,
                "confidence": item.confidence,
                "payload": item.metadata,
            }
            for item in (canonical.evidence or [])
        ]
        contradictions = [
            {
                "claim_a": contradiction.claim_a,
                "claim_b": contradiction.claim_b,
                "severity": contradiction.severity,
                "resolvable": contradiction.resolvable,
                "recommended_action": contradiction.recommended_action,
            }
            for contradiction in (canonical.contradictions or [])
        ]
        confidence = canonical.assessment.confidence if canonical.assessment else 0.0
        return cls(
            summary=canonical.conclusion,
            evidence=evidence,
            hypotheses=hypotheses,
            confidence=confidence,
            diagnostics=canonical.diagnostics or {},
            success=canonical.status not in ("failed", "budget_exhausted"),
            degraded=canonical.status in ("failed", "budget_exhausted"),
            reasoning_type=(
                canonical.diagnostics.get("reasoning_type", "reasoning")
                if canonical.diagnostics
                else "reasoning"
            ),
            contradictions_found=contradictions,
            needs_human_confirmation=canonical.status == "needs_human_confirmation",
        )


@dataclass(slots=True)
class OrchestrationResult:
    final_text: str
    reasoning_result: Optional[ReasoningResult] = None
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    memory_reads: List[Dict[str, Any]] = field(default_factory=list)
    memory_writes: List[Dict[str, Any]] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)


class IntentEngine(Protocol):
    def detect(self, request: RuntimeRequest) -> IntentSignal: ...


class PredictorEngine(Protocol):
    def predict(self, request: RuntimeRequest, intent: IntentSignal) -> PredictorSignal: ...


class KireEngine(Protocol):
    def enrich(
        self,
        request: RuntimeRequest,
        intent: IntentSignal,
        predictors: PredictorSignal,
    ) -> KireSignal: ...


class RbacValidator(Protocol):
    def validate(
        self,
        user: UserContext,
        intent: IntentSignal,
        routing: RoutingDecision,
    ) -> None: ...


class RoutingEngine(Protocol):
    def decide(
        self,
        request: RuntimeRequest,
        intent: IntentSignal,
        predictors: PredictorSignal,
        kire: KireSignal,
    ) -> RoutingDecision: ...


class KROOrchestrator(Protocol):
    def run(self, request: ReasoningRequest) -> ReasoningResult: ...


class LangGraphRuntime(Protocol):
    def run(self, orchestration_input: OrchestrationInput) -> OrchestrationResult: ...


class CorrelationIdFactory:
    def create(self, request: RuntimeRequest) -> str:
        base = request.user.user_id or "anonymous"
        thread = request.user.thread_id or "no-thread"
        return f"cx-{base}-{thread}"
