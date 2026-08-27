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


def _topology_from_execution_mode(
    mode: RuntimeExecutionMode, graph_required: bool
) -> ExecutionTopology:
    if mode == RuntimeExecutionMode.DEGRADED:
        return ExecutionTopology.DIRECT
    if graph_required:
        return ExecutionTopology.WORKFLOW
    return ExecutionTopology.DIRECT


@dataclass
class ExecutionDecision:
    """CORTEX-produced, runtime-consumed cognitive execution recommendation.

    CORTEX decides what kind of execution a request needs. RuntimePolicy decides
    what is authorized, and Runtime executes the resulting plan. Capability and
    reasoning-mode domains are intentionally distinct.
    """

    execution_mode: RuntimeExecutionMode = RuntimeExecutionMode.DIRECT
    graph_required: bool = False
    topology: ExecutionTopology = ExecutionTopology.DIRECT

    intent: str = "general_assist"
    intent_confidence: float = 0.0
    risk_level: RiskLevel = RiskLevel.LOW

    reasoning_depth: str = "standard"
    reasoning_modes: List[str] = field(default_factory=list)
    memory_recall_required: bool = False
    # Fail closed. This becomes true only after RuntimePolicy grants memory.write.
    memory_write_allowed: bool = False
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
    max_model_calls: int = 10
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
        if self.max_steps < 0:
            raise ValueError("max_steps must be non-negative")
        if self.max_model_calls < 0:
            raise ValueError("max_model_calls must be non-negative")
        if self.time_budget_ms < 0:
            raise ValueError("time_budget_ms must be non-negative")
        if self.token_budget < 0:
            raise ValueError("token_budget must be non-negative")

        if (
            self.topology == ExecutionTopology.DIRECT
            and self.execution_mode == RuntimeExecutionMode.GRAPH
        ):
            self.topology = ExecutionTopology.WORKFLOW
        if self.topology == ExecutionTopology.DIRECT and self.graph_required:
            self.topology = ExecutionTopology.WORKFLOW
        if (
            self.topology == ExecutionTopology.WORKFLOW
            and not self.graph_required
            and self.execution_mode != RuntimeExecutionMode.GRAPH
        ):
            self.graph_required = True

        # Compatibility bridge for the pre-convergence ChatRuntime persistence
        # call site, which currently invokes persistence only on the recall path.
        # Authorization still comes exclusively from RuntimePolicy. Remove this
        # bridge when ChatRuntime checks memory_write_allowed independently.
        if self.memory_write_allowed and not self.memory_recall_required:
            self.memory_recall_required = True
            if "compat_memory_write_requires_recall" not in self.reason_codes:
                self.reason_codes.append("compat_memory_write_requires_recall")

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
