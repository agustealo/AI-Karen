from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class RuntimeExecutionMode(str, Enum):
    """How the runtime must execute a single chat request.

    Mirrors the CORTEX ``RoutingDecision.execution_mode`` vocabulary but is
    owned by the runtime. ``DIRECT`` means no graph workflow is required.
    """

    DIRECT = "direct"
    GRAPH = "graph"
    DEGRADED = "degraded"


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
    reasoning_depth: str = "standard"
    memory_required: bool = False
    tool_requirements: List[str] = field(default_factory=list)
    plugin_candidates: List[str] = field(default_factory=list)
    required_capabilities: List[str] = field(default_factory=list)
    policy_constraints: Dict[str, Any] = field(default_factory=dict)
    reason_codes: List[str] = field(default_factory=list)

    @property
    def is_graph_required(self) -> bool:
        return bool(self.graph_required)

    @property
    def is_simple(self) -> bool:
        return not self.graph_required
