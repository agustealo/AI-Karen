from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.runtime.contracts import ExecutionTopology


class RuntimeExecutionMode(str, Enum):
    """Backward-compatible runtime mode alias for ExecutionTopology."""

    DIRECT = "direct"
    GRAPH = "graph"
    DEGRADED = "degraded"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def _topology_from_execution_mode(mode: RuntimeExecutionMode, graph_required: bool) -> ExecutionTopology:
    if mode == RuntimeExecutionMode.DEGRADED:
        return ExecutionTopology.DIRECT
    if graph_required:
        return ExecutionTopology.WORKFLOW
    return ExecutionTopology.DIRECT


@dataclass
class ExecutionDecision:
    """CORTEX-produced, runtime-consumed execution decision.

    CORTEX decides *what kind* of execution is required. It never executes.
    The runtime consumes this to route to ExpressionGateway (simple) or the
    WorkflowRuntime/LangGraph adapter (graph-required).

    This is the single decision contract between CORTEX and ChatRuntime.
    """

    execution_mode: RuntimeExecutionMode = RuntimeExecutionMode.DIRECT
    graph_required: bool = False
    topology: ExecutionTopology = field(default_factory=ExecutionTopology.DIRECT)

    intent: str = "general_assist"
    intent_confidence: float = 0.0
    risk_level: RiskLevel = RiskLevel.LOW

    reasoning_depth: str = "standard"
    memory_recall_required: bool = False
    memory_write_allowed: bool = True
    memory_scope: str = "session"
    memory_top_k: int = 10
    memory_classes: List[str] = field(default_factory=list)

    tool_requirements: List[str] = field(default_factory=list)
    plugin_candidates: List[str] = field(default_factory=list)
    required_capabilities: List[str] = field(default_factory=list)
    forbidden_capabilities: List[str] = field(default_factory=list)

    requires_human_gate: bool = False
    requires_resumability: bool = False
    requires_parallel_execution: bool = False
    requires_agent_delegation: bool = False

    max_steps: int = 10
    time_budget_ms: int = 30000
    token_budget: int = 4096

    workflow_id: Optional[str] = None
    workflow_version: str = "v1"

    policy_decision_id: Optional[str] = None
    policy_version: str = "v1"
    policy_reason_codes: List[str] = field(default_factory=list)

    reason_codes: List[str] = field(default_factory=list)
    policy_constraints: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.topology == ExecutionTopology.DIRECT and self.execution_mode == RuntimeExecutionMode.GRAPH:
            self.topology = ExecutionTopology.WORKFLOW
        if self.topology == ExecutionTopology.DIRECT and self.graph_required:
            self.topology = ExecutionTopology.WORKFLOW
        if self.topology == ExecutionTopology.WORKFLOW and not self.graph_required and self.execution_mode != RuntimeExecutionMode.GRAPH:
            self.graph_required = True

    @property
    def is_graph_required(self) -> bool:
        return bool(self.graph_required) or self.topology in {
            ExecutionTopology.WORKFLOW,
            ExecutionTopology.MULTI_AGENT,
            ExecutionTopology.REASONING,
        }

    @property
    def is_simple(self) -> bool:
        return not self.is_graph_required

    @property
    def memory_required(self) -> bool:
        """Backward-compatible alias for memory_recall_required."""
        return self.memory_recall_required

    @memory_required.setter
    def memory_required(self, value: bool) -> None:
        self.memory_recall_required = bool(value)
