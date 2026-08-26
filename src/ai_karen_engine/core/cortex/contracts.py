from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from ai_karen_engine.core.contracts.cognitive import ReasoningDepth
from ai_karen_engine.core.contracts.values import JsonMap
from ai_karen_engine.core.reasoning.contracts import (
    ReasoningBudget,
    ReasoningEvidence,
    ReasoningRequest as CanonicalReasoningRequest,
    ReasoningResult as CanonicalReasoningResult,
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
    subtype: str | None = None
    secondary_intents: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
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
    reasoning_modes: list[str] = field(default_factory=list)
    strategy_hint: str | None = None
    should_use_memory: bool = True
    should_use_tools: bool = False
    should_use_retrieval_reasoning: bool = False
    should_use_causal_reasoning: bool = False
    should_use_graph_reasoning: bool = False
    should_self_refine: bool = False
    should_verify: bool = False


@dataclass(slots=True)
class RoutingDecision:
    """CORTEX recommendation consumed by Runtime.

    This contract is not an authorization grant. RuntimePolicy remains the sole
    authority for executable capabilities, tools, plugins, and durable writes.
    """

    route_family: RouteFamily
    execution_mode: ExecutionMode
    target_graph: str | None = None
    target_service: str | None = None
    target_plugin: str | None = None
    target_agent: str | None = None
    allow_reasoning: bool = False
    allow_tools: bool = False
    allow_memory_read: bool = True
    # Fail closed. CORTEX may recommend persistence, but RuntimePolicy must grant it.
    allow_memory_write: bool = False
    require_approval_gate: bool = False


@dataclass(slots=True)
class UserContext:
    user_id: str
    tenant_id: str
    roles: list[str] = field(default_factory=list)
    session_id: str | None = None
    thread_id: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("CORTEX requires explicit non-default tenant_id")


@dataclass(slots=True)
class RuntimeRequest:
    message: str
    user: UserContext
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CortexOutput:
    intent: IntentSignal
    predictors: PredictorSignal
    kire: KireSignal
    routing: RoutingDecision
    correlation_id: str
    audit_tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OrchestrationInput:
    message: str
    user: UserContext
    metadata: dict[str, Any]
    cortex: CortexOutput


@dataclass(slots=True)
class ReasoningRequest:
    """Legacy CORTEX reasoning envelope adapted to the canonical contract."""

    message: str
    user: UserContext
    memory_context: dict[str, Any]
    tool_context: dict[str, Any]
    intent: IntentSignal
    predictors: PredictorSignal
    kire: KireSignal
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_canonical(self) -> CanonicalReasoningRequest:
        evidence: list[ReasoningEvidence] = []
        recall = (self.memory_context or {}).get("recall") or []
        for index, item in enumerate(recall):
            if not isinstance(item, dict):
                continue
            evidence.append(
                ReasoningEvidence(
                    evidence_id=str(item.get("id", f"mem-{index}")),
                    type="memory",
                    source="memory_recall",
                    source_ref=str(item.get("timestamp", "")),
                    content=str(item.get("content", "")),
                    relevance=float(item.get("relevance", 0.5)),
                    confidence=float(item.get("confidence", 0.5)),
                    tenant_id=self.user.tenant_id,
                )
            )

        correlation_id = str(self.metadata.get("correlation_id", ""))
        return CanonicalReasoningRequest(
            request_id=correlation_id,
            correlation_id=correlation_id,
            tenant_id=self.user.tenant_id,
            user_id=self.user.user_id,
            conversation_id=self.user.thread_id,
            objective=self.message,
            reasoning_modes=list(self.kire.reasoning_modes),
            evidence=evidence,
            constraints={
                "reasoning_depth": self.kire.reasoning_depth.value,
                "should_self_refine": self.kire.should_self_refine,
                "should_verify": self.kire.should_verify,
                "should_use_causal": self.kire.should_use_causal_reasoning,
                "should_use_graph": self.kire.should_use_graph_reasoning,
                "should_use_retrieval": self.kire.should_use_retrieval_reasoning,
            },
            policy_decision_id=str(self.metadata.get("policy_decision_id", "")),
            budget=ReasoningBudget(),
            metadata=dict(self.metadata),
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
                thread_id=canonical.conversation_id,
            ),
            memory_context={},
            tool_context={},
            intent=IntentSignal(primary_intent="reasoning"),
            predictors=PredictorSignal(),
            kire=KireSignal(
                requires_reasoning=True,
                reasoning_depth=depth,
                reasoning_modes=list(canonical.reasoning_modes),
                should_use_memory=bool(canonical.evidence),
                should_use_tools=False,
                should_use_retrieval_reasoning=bool(canonical.constraints.get("should_use_retrieval", False)),
                should_use_causal_reasoning=bool(canonical.constraints.get("should_use_causal", False)),
                should_use_graph_reasoning=bool(canonical.constraints.get("should_use_graph", False)),
                should_self_refine=bool(canonical.constraints.get("should_self_refine", False)),
                should_verify=bool(canonical.constraints.get("should_verify", False)),
            ),
            metadata=dict(canonical.metadata),
        )


@dataclass(slots=True)
class ReasoningResult:
    """Legacy result adapter. Canonical confidence is explicitly converted."""

    summary: str
    evidence: list[JsonMap] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    confidence: float = 0.0
    verification_notes: list[str] = field(default_factory=list)

    @classmethod
    def from_canonical(cls, canonical: CanonicalReasoningResult) -> "ReasoningResult":
        return cls(
            summary=canonical.conclusion,
            evidence=[{"id": item.evidence_id, "content": item.content} for item in canonical.evidence],
            hypotheses=[item.statement for item in canonical.hypotheses],
            confidence=float(canonical.assessment.confidence),
            verification_notes=list(canonical.assessment.uncertainty_reasons),
        )


class CorrelationIdFactory(Protocol):
    def create(self, request: RuntimeRequest) -> str: ...
