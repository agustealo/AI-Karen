from __future__ import annotations

import os
from typing import Optional

from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionRequest
from ai_karen_engine.core.runtime.execution_decision import (
    ExecutionDecision,
    RuntimeExecutionMode,
)

# Safety escape hatch: force every request through the graph workflow path.
# Useful for rollback if the simple/ExpressionGateway path misbehaves in prod.
_FORCE_GRAPH_ENV = "KARI_RUNTIME_FORCE_GRAPH"


class CortexExecutionDecider:
    """Single CORTEX entry point for runtime execution routing.

    CORTEX decides *what kind* of execution a request needs. It inspects
    structured intent signals (tool/plugin requirements, capabilities, explicit
    graph requests, policy constraints) and returns an :class:`ExecutionDecision`.

    It does NOT execute anything: no provider call, no graph invocation, no
    memory recall. The runtime consumes the decision to route execution.
    """

    def __init__(self, *, force_graph: Optional[bool] = None):
        self._force_graph = (
            force_graph
            if force_graph is not None
            else os.environ.get(_FORCE_GRAPH_ENV, "false").lower() in ("1", "true", "yes")
        )

    async def decide(self, request: ChatExecutionRequest) -> ExecutionDecision:
        meta = request.metadata or {}
        reason_codes: list[str] = []

        tool_requirements = list(meta.get("tool_requirements") or [])
        plugin_candidates = list(meta.get("plugin_candidates") or [])
        required_capabilities = list(meta.get("required_capabilities") or [])
        policy_constraints = dict(meta.get("policy_constraints") or {})

        graph_required = False

        # Explicit structural signals take precedence.
        if meta.get("graph_required") or meta.get("force_graph"):
            graph_required = True
            reason_codes.append("explicit_graph_request")

        # CORTEX-class signals: tools / plugins / workflow capabilities require a graph.
        if tool_requirements or plugin_candidates:
            graph_required = True
            reason_codes.append("tool_or_plugin_requirements")
        if "workflow" in required_capabilities or "agent" in required_capabilities:
            graph_required = True
            reason_codes.append("workflow_capability")

        # Reserved seam: a full model-backed CORTEX RoutingDecision may override
        # here. The deterministic signals above are sufficient for routing until
        # that integration is wired in RC1.2.x.

        # Operational safety override (rollback).
        if self._force_graph:
            graph_required = True
            reason_codes.append("force_graph_override")

        execution_mode = (
            RuntimeExecutionMode.GRAPH if graph_required else RuntimeExecutionMode.DIRECT
        )

        return ExecutionDecision(
            execution_mode=execution_mode,
            graph_required=graph_required,
            reasoning_depth=str(meta.get("reasoning_depth", "standard")),
            memory_required=bool(meta.get("memory_required", False)) and not graph_required,
            tool_requirements=tool_requirements,
            plugin_candidates=plugin_candidates,
            required_capabilities=required_capabilities,
            policy_constraints=policy_constraints,
            reason_codes=reason_codes,
        )


_decider: Optional[CortexExecutionDecider] = None


def get_cortex_execution_decider() -> CortexExecutionDecider:
    """Return the singleton CORTEX execution decider."""
    global _decider
    if _decider is None:
        _decider = CortexExecutionDecider()
    return _decider
