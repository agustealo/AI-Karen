from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional
import uuid

from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    DegradationState,
    ExecutionBudget,
    ExecutionTopology,
)


@dataclass(frozen=True)
class RuntimePolicyDecision:
    """Canonical runtime policy decision produced from CORTEX output.

    Enhanced to carry AuthorizedExecutionPlan fields while preserving
    backward-compatible attributes used by existing callers and tests.
    """

    policy_token: str
    source: str
    requires_deep_reasoning: bool
    requires_medusa: bool
    correlation_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)

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

    @classmethod
    def from_cortex(
        cls,
        cortex_output: Optional[Mapping[str, Any]],
        *,
        correlation_id: Optional[str] = None,
        source: str = "cortex",
    ) -> "RuntimePolicyDecision":
        payload = dict(cortex_output or {})
        meta = dict(payload.get("metadata", {}))
        token = str(payload.get("policy_token") or uuid.uuid4())
        corr = str(correlation_id or payload.get("correlation_id") or uuid.uuid4())
        requires_deep_reasoning = bool(payload.get("requires_deep_reasoning", False))
        requires_medusa = bool(payload.get("requires_medusa", False))

        topology = ExecutionTopology.DIRECT
        if requires_deep_reasoning:
            topology = ExecutionTopology.REASONING
        if requires_medusa:
            topology = ExecutionTopology.MULTI_AGENT
        routing = payload.get("routing") if isinstance(payload.get("routing"), dict) else {}
        execution_mode = str(routing.get("execution_mode") or payload.get("execution_mode") or "direct")
        if execution_mode == "langgraph":
            topology = ExecutionTopology.WORKFLOW

        return cls(
            policy_token=token,
            source=source,
            requires_deep_reasoning=requires_deep_reasoning,
            requires_medusa=requires_medusa,
            correlation_id=corr,
            metadata=meta,
            topology=topology,
            allowed_capabilities=list(payload.get("allowed_capabilities") or []),
            allowed_tools=list(payload.get("allowed_tools") or []),
            allowed_plugins=list(payload.get("allowed_plugins") or []),
            allowed_agents=list(payload.get("allowed_agents") or []),
            provider_constraints=dict(payload.get("provider_constraints") or {}),
            memory_scope=str(payload.get("memory_scope") or "session"),
            resource_scope=dict(payload.get("resource_scope") or {}),
            approval_requirements=list(payload.get("approval_requirements") or []),
            reasoning_modes=list(payload.get("reasoning_modes") or []),
            workflow_id=payload.get("workflow_id"),
            agent_topology=payload.get("agent_topology"),
            degraded_allowed=bool(payload.get("degraded_allowed", True)),
            degradation_state=payload.get("degradation_state"),
            audit_context=dict(payload.get("audit_context") or {}),
        )

    def to_telemetry_metadata(self) -> Dict[str, Any]:
        return {
            "policy_token": self.policy_token,
            "policy_source": self.source,
            "requires_deep_reasoning": self.requires_deep_reasoning,
            "requires_medusa": self.requires_medusa,
            "topology": self.topology.value,
            "correlation_id": self.correlation_id,
            **self.metadata,
        }

    def to_authorized_plan(self) -> AuthorizedExecutionPlan:
        """Convert to the canonical AuthorizedExecutionPlan consumed by RuntimeExecutor."""
        return AuthorizedExecutionPlan(
            execution_id=self.policy_token,
            policy_decision_id=self.policy_token,
            topology=self.topology,
            allowed_capabilities=self.allowed_capabilities,
            allowed_tools=self.allowed_tools,
            allowed_plugins=self.allowed_plugins,
            allowed_agents=self.allowed_agents,
            provider_constraints=self.provider_constraints,
            memory_scope=self.memory_scope,
            resource_scope=self.resource_scope,
            budget=self.budget,
            approval_requirements=self.approval_requirements,
            reasoning_modes=self.reasoning_modes,
            workflow_id=self.workflow_id,
            agent_topology=self.agent_topology,
            degraded_allowed=self.degraded_allowed,
            degradation_state=self.degradation_state,
            audit_context=self.audit_context,
        )
