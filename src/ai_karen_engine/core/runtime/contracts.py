from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ExecutionTopology(str, Enum):
    """Canonical execution topology for a single request.

    DEGRADED is intentionally NOT a topology. It is execution state/metadata.
    """

    DIRECT = "direct"
    REASONING = "reasoning"
    WORKFLOW = "workflow"
    MULTI_AGENT = "multi_agent"


class ResponseSource(str, Enum):
    """Canonical provenance for every final result."""

    MODEL = "model"
    TOOL = "tool"
    PLUGIN = "plugin"
    AGENT = "agent"
    WORKFLOW = "workflow"
    CACHED = "cached"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"


@dataclass(slots=True)
class ExecutionBudget:
    """Resource boundaries enforced by RuntimeExecutor."""

    max_duration_ms: int = 30000
    max_model_calls: int = 10
    max_reasoning_steps: int = 5
    max_tool_calls: int = 10
    max_agent_turns: int = 5
    max_parallelism: int = 4
    max_input_tokens: int = 8192
    max_output_tokens: int = 4096
    max_memory_items: int = 20
    max_external_requests: int = 5


class ExecutionBudgetMeter:
    """Track consumption against an ExecutionBudget for one request."""

    def __init__(self, budget: ExecutionBudget) -> None:
        self._budget = budget
        self._model_calls = 0
        self._reasoning_steps = 0
        self._tool_calls = 0
        self._agent_turns = 0
        self._external_requests = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._start_ms: float = 0.0
        self._exhausted = False
        self._lock = asyncio.Lock()

    def start(self) -> None:
        self._start_ms = __import__("time").time() * 1000.0

    async def check_duration(self) -> bool:
        async with self._lock:
            if self._exhausted:
                return False
            elapsed = __import__("time").time() * 1000.0 - self._start_ms
            if elapsed >= self._budget.max_duration_ms:
                self._exhausted = True
                return False
            return True

    async def reserve_model_call(self) -> bool:
        async with self._lock:
            if self._exhausted:
                return False
            self._model_calls += 1
            if self._model_calls > self._budget.max_model_calls:
                self._exhausted = True
                return False
            return True

    async def reserve_reasoning_step(self) -> bool:
        async with self._lock:
            if self._exhausted:
                return False
            self._reasoning_steps += 1
            if self._reasoning_steps > self._budget.max_reasoning_steps:
                self._exhausted = True
                return False
            return True

    async def reserve_tool_call(self) -> bool:
        async with self._lock:
            if self._exhausted:
                return False
            self._tool_calls += 1
            if self._tool_calls > self._budget.max_tool_calls:
                self._exhausted = True
                return False
            return True

    async def reserve_agent_turn(self) -> bool:
        async with self._lock:
            if self._exhausted:
                return False
            self._agent_turns += 1
            if self._agent_turns > self._budget.max_agent_turns:
                self._exhausted = True
                return False
            return True

    async def reserve_external_request(self) -> bool:
        async with self._lock:
            if self._exhausted:
                return False
            self._external_requests += 1
            if self._external_requests > self._budget.max_external_requests:
                self._exhausted = True
                return False
            return True

    async def add_input_tokens(self, count: int) -> bool:
        async with self._lock:
            if self._exhausted:
                return False
            self._input_tokens += count
            if self._input_tokens > self._budget.max_input_tokens:
                self._exhausted = True
                return False
            return True

    async def add_output_tokens(self, count: int) -> bool:
        async with self._lock:
            if self._exhausted:
                return False
            self._output_tokens += count
            if self._output_tokens > self._budget.max_output_tokens:
                self._exhausted = True
                return False
            return True

    async def consume_model_call(self) -> bool:
        return await self.reserve_model_call()

    async def consume_reasoning_step(self) -> bool:
        return await self.reserve_reasoning_step()

    async def consume_tool_call(self) -> bool:
        return await self.reserve_tool_call()

    async def consume_agent_turn(self) -> bool:
        return await self.reserve_agent_turn()

    async def consume_external_request(self) -> bool:
        return await self.reserve_external_request()

    @property
    def exhausted(self) -> bool:
        return self._exhausted

    @property
    def model_calls(self) -> int:
        return self._model_calls

    @property
    def reasoning_steps(self) -> int:
        return self._reasoning_steps

    @property
    def tool_calls(self) -> int:
        return self._tool_calls

    @property
    def agent_turns(self) -> int:
        return self._agent_turns

    @property
    def external_requests(self) -> int:
        return self._external_requests

    @property
    def input_tokens(self) -> int:
        return self._input_tokens

    @property
    def output_tokens(self) -> int:
        return self._output_tokens


@dataclass(slots=True)
class DecisionProvenance:
    """Provenance for any decision made in the control plane."""

    decision_id: str
    decision_type: str
    owner: str
    version: str
    inputs_used: List[str] = field(default_factory=list)
    signal_refs: List[str] = field(default_factory=list)
    rule_version: str = "v1"
    confidence: float = 0.0
    created_at: Optional[str] = None


@dataclass(slots=True)
class DegradationState:
    """Canonical degraded-mode state owned by RuntimeResilience."""

    degraded: bool = False
    reason_code: Optional[str] = None
    level: str = "none"
    original_requirement: Optional[str] = None
    actual_execution: Optional[str] = None
    capabilities_lost: List[str] = field(default_factory=list)
    fallback_level: int = 0


@dataclass(slots=True)
class ResponseProvenance:
    """Provenance attached to every final result."""

    response_source: ResponseSource = ResponseSource.UNAVAILABLE
    provider: Optional[str] = None
    model: Optional[str] = None
    engine: Optional[str] = None
    fallback_level: int = 0
    degradation_reason: Optional[str] = None
    correlation_id: Optional[str] = None
    decision_id: Optional[str] = None


@dataclass(slots=True)
class ExecutionContext:
    """Base scoped context for any executor."""

    request_id: str
    correlation_id: str
    user_id: str
    tenant_id: str = "default"
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    policy_decision_id: Optional[str] = None
    allowed_capabilities: List[str] = field(default_factory=list)
    resource_scope: Dict[str, Any] = field(default_factory=dict)
    deadline: Optional[str] = None
    budget: Optional[ExecutionBudget] = None
    audit_context: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AuthorizedExecutionPlan:
    """Single runtime instruction after RuntimePolicy evaluation.

    Nothing below RuntimePolicy needs to re-decide authorization. The
    ``deep``/``standard`` handling below is a compatibility shim for the
    pre-typed ChatRuntime plan builder and must be removed when that caller
    forwards ``ExecutionDecision.reasoning_modes`` directly.
    """

    execution_id: str
    policy_decision_id: str
    topology: ExecutionTopology = ExecutionTopology.DIRECT
    allowed_capabilities: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    allowed_plugins: List[str] = field(default_factory=list)
    allowed_agents: List[str] = field(default_factory=list)
    provider_constraints: Dict[str, Any] = field(default_factory=dict)
    memory_scope: str = "session"
    resource_scope: Dict[str, Any] = field(default_factory=dict)
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)
    approval_requirements: List[str] = field(default_factory=list)
    reasoning_modes: List[str] = field(default_factory=list)
    workflow_id: Optional[str] = None
    agent_topology: Optional[str] = None
    degraded_allowed: bool = True
    degradation_state: Optional[DegradationState] = None
    audit_context: Dict[str, Any] = field(default_factory=dict)
    provenance: Optional[DecisionProvenance] = None

    def __post_init__(self) -> None:
        raw_modes = [str(mode).strip().lower() for mode in self.reasoning_modes if str(mode).strip()]
        if raw_modes == ["standard"]:
            self.reasoning_modes = []
            return
        if raw_modes == ["deep"]:
            self.reasoning_modes = [
                "causal",
                "evidence_synthesis",
                "verification",
                "refinement",
                "metacognition",
            ]
            return
        self.reasoning_modes = raw_modes


@dataclass(slots=True)
class CapabilityDescriptor:
    """Common descriptor protocol for registries to expose."""

    capability_id: str
    version: str
    type: str
    capabilities: List[str] = field(default_factory=list)
    required_permissions: List[str] = field(default_factory=list)
    resource_requirements: Dict[str, Any] = field(default_factory=dict)
    modalities: List[str] = field(default_factory=list)
    locality: str = "any"
    tenant_safe: bool = True
    supports_streaming: bool = False
    supports_interrupt: bool = False
    health_state: str = "healthy"


@dataclass(slots=True)
class ExecutionRequirements:
    """CORTEX-produced requirements before RuntimePolicy evaluation.

    This is an advisory signal contract. It must never contain an implicit
    authorization grant. RuntimePolicy is the only owner that can authorize
    capabilities or durable writes.
    """

    request_id: str
    correlation_id: str
    intent: str = "general_assist"
    intent_confidence: float = 0.0
    required_capabilities: List[str] = field(default_factory=list)
    forbidden_capabilities: List[str] = field(default_factory=list)
    topology_signals: Dict[str, Any] = field(default_factory=dict)
    reasoning_depth: str = "standard"
    reasoning_modes: List[str] = field(default_factory=list)
    memory_recall_required: bool = False
    memory_write_allowed: bool = False
    memory_scope: str = "session"
    memory_top_k: int = 10
    memory_classes: List[str] = field(default_factory=list)
    tool_requirements: List[str] = field(default_factory=list)
    plugin_candidates: List[str] = field(default_factory=list)
    requires_human_gate: bool = False
    requires_resumability: bool = False
    requires_parallel_execution: bool = False
    requires_agent_delegation: bool = False
    max_steps: int = 10
    time_budget_ms: int = 30000
    token_budget: int = 4096
    workflow_id: Optional[str] = None
    workflow_version: str = "v1"
    risk_signals: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RuntimeCapabilitiesSnapshot:
    """Backend-confirmed capability snapshot for UI/transport consumption."""

    available_providers: List[str] = field(default_factory=list)
    available_models: List[str] = field(default_factory=list)
    available_tools: List[str] = field(default_factory=list)
    available_workflows: List[str] = field(default_factory=list)
    available_agents: List[str] = field(default_factory=list)
    available_reasoning_modes: List[str] = field(default_factory=list)
    available_plugins: List[str] = field(default_factory=list)
    degraded_state: bool = False
    degradation_reason: Optional[str] = None
    runtime_mode: str = "normal"
    maintenance_active: bool = False


@dataclass(slots=True)
class GenerationRequest:
    """Canonical request for any model generation."""

    request_id: str
    correlation_id: str
    prompt_contract_id: Optional[str] = None
    prompt_version: Optional[str] = None
    messages: List[Dict[str, Any]] = field(default_factory=list)
    context_sections: List[Dict[str, Any]] = field(default_factory=list)
    required_capabilities: List[str] = field(default_factory=list)
    forbidden_capabilities: List[str] = field(default_factory=list)
    provider_constraints: Dict[str, Any] = field(default_factory=dict)
    model_constraints: Dict[str, Any] = field(default_factory=dict)
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    response_schema: Dict[str, Any] = field(default_factory=dict)
    streaming: bool = False
    policy_decision_id: Optional[str] = None
    execution_context: Optional[ExecutionContext] = None
    budget: Optional[ExecutionBudget] = None


class ActionExecutionGate:
    """Side-effect enforcement point for all external mutations.

    Any component that mutates the outside world must pass through this gate.
    The gate checks the AuthorizedExecutionPlan and never decides policy itself.
    """

    @staticmethod
    async def authorize(plan: AuthorizedExecutionPlan, action: str) -> bool:
        if plan is None:
            return False
        if (
            not plan.degraded_allowed
            and plan.degradation_state
            and plan.degradation_state.degraded
        ):
            return False
        allowed_tools = set(plan.allowed_tools)
        allowed_plugins = set(plan.allowed_plugins)
        allowed_agents = set(plan.allowed_agents)
        if action in allowed_tools or action in allowed_plugins or action in allowed_agents:
            return True
        if not plan.allowed_capabilities:
            return False
        return any(cap in plan.allowed_capabilities for cap in ["*", action])
