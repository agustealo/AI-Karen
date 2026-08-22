from __future__ import annotations

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
    """Canonical degraded-mode state.

    RuntimeResilience owns this. Specialists report failure only.
    """

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
    """Base scoped context for any executor.

    No raw giant dict. Specialized contexts extend this.
    """

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

    Nothing below RuntimePolicy needs to re-decide authorization.
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
