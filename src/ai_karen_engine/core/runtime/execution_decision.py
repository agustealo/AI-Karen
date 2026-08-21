from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RuntimeExecutionMode(str, Enum):
    """How the runtime must execute a single chat request."""

    DIRECT = "direct"
    GRAPH = "graph"
    DEGRADED = "degraded"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ExecutionDecision:
    """CORTEX-produced, runtime-consumed execution decision.

    CORTEX decides *what kind* of execution is required. It never executes.
    The runtime consumes this to route to ExpressionGateway (simple) or the
    WorkflowRuntime/LangGraph adapter (graph-required).

    This is the single decision contract between CORTEX and ChatRuntime.
    """

    execution_mode: RuntimeExecutionMode
    graph_required: bool

    intent: str = "general_assist"
    intent_confidence: float = 0.0
    risk_level: RiskLevel = RiskLevel.LOW

    reasoning_depth: str = "standard"
    memory_required: bool = False
    memory_scope: str = "session"

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

    reason_codes: List[str] = field(default_factory=list)
    policy_constraints: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_graph_required(self) -> bool:
        return bool(self.graph_required)

    @property
    def is_simple(self) -> bool:
        return not self.graph_required
