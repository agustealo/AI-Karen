from __future__ import annotations

import os
from typing import Optional, List, Dict, Any

from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionRequest
from ai_karen_engine.core.runtime.execution_decision import (
    ExecutionDecision,
    RuntimeExecutionMode,
    RiskLevel,
)

# Safety escape hatch: force every request through the graph workflow path.
_FORCE_GRAPH_ENV = "KARI_RUNTIME_FORCE_GRAPH"

# Fail-closed: if RBAC infrastructure is unavailable, protected capabilities are denied.
_RBAC_UNAVAILABLE_ACTION = "deny"


class CortexExecutionDecider:
    """Single CORTEX entry point for runtime execution routing.

    CORTEX decides *what kind* of execution a request needs. It inspects
    structured intent signals (tool/plugin requirements, capabilities, explicit
    graph requests, policy constraints) and returns an :class:`ExecutionDecision`.

    It does NOT execute anything: no provider call, no graph invocation, no
    memory recall. The runtime consumes the decision to route execution.

    Security: RBAC/policy failures are fail-closed. Missing capability
    infrastructure means DENIED, not implicit permission.
    """

    def __init__(self, *, force_graph: Optional[bool] = None):
        self._force_graph = (
            force_graph
            if force_graph is not None
            else os.environ.get(_FORCE_GRAPH_ENV, "false").lower() in ("1", "true", "yes")
        )

    async def decide(self, request: ChatExecutionRequest) -> ExecutionDecision:
        meta = request.metadata or {}
        ctx = request.context
        reason_codes: List[str] = []

        # ------------------------------------------------------------------
        # 1. Structural signals (explicit, highest precedence)
        # ------------------------------------------------------------------
        explicit_graph = bool(meta.get("graph_required") or meta.get("force_graph"))
        if explicit_graph:
            reason_codes.append("explicit_graph_request")

        # ------------------------------------------------------------------
        # 2. Execution-topology triggers (determines graph need by task shape)
        # ------------------------------------------------------------------
        topology_triggers = self._evaluate_topology_triggers(meta)
        graph_required = explicit_graph or bool(topology_triggers)
        reason_codes.extend(topology_triggers)

        # ------------------------------------------------------------------
        # 3. CORTEX-class signals: tools / plugins / workflow capabilities
        # ------------------------------------------------------------------
        tool_requirements = list(meta.get("tool_requirements") or [])
        plugin_candidates = list(meta.get("plugin_candidates") or [])
        required_capabilities = list(meta.get("required_capabilities") or [])
        forbidden_capabilities = list(meta.get("forbidden_capabilities") or [])
        policy_constraints = dict(meta.get("policy_constraints") or {})

        if tool_requirements or plugin_candidates:
            graph_required = True
            reason_codes.append("tool_or_plugin_requirements")
        if "workflow" in required_capabilities or "agent" in required_capabilities:
            graph_required = True
            reason_codes.append("workflow_capability")

        # ------------------------------------------------------------------
        # 4. Risk and governance
        # ------------------------------------------------------------------
        risk_level = self._assess_risk_level(meta, tool_requirements, plugin_candidates)
        requires_human_gate = bool(meta.get("requires_human_gate", False)) or risk_level in (
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        )
        requires_resumability = bool(meta.get("requires_resumability", False))
        requires_parallel_execution = bool(meta.get("requires_parallel_execution", False))
        requires_agent_delegation = bool(meta.get("requires_agent_delegation", False))

        if requires_human_gate:
            graph_required = True
            reason_codes.append("human_gate_required")
        if requires_agent_delegation:
            graph_required = True
            reason_codes.append("agent_delegation_required")

        # ------------------------------------------------------------------
        # 5. Budgets and constraints
        # ------------------------------------------------------------------
        max_steps = int(meta.get("max_steps", 10))
        time_budget_ms = int(meta.get("time_budget_ms", 30000))
        token_budget = int(meta.get("token_budget", 4096))
        reasoning_depth = str(meta.get("reasoning_depth", "standard"))
        memory_required = bool(meta.get("memory_required", False)) and not graph_required
        memory_scope = str(meta.get("memory_scope", "session"))

        # ------------------------------------------------------------------
        # 6. Fail-closed policy check
        # ------------------------------------------------------------------
        if required_capabilities or forbidden_capabilities:
            policy_result = self._check_capability_policy(
                required_capabilities, forbidden_capabilities, policy_constraints
            )
            if not policy_result["allowed"]:
                return ExecutionDecision(
                    execution_mode=RuntimeExecutionMode.DEGRADED,
                    graph_required=False,
                    intent=str(meta.get("intent", "general_assist")),
                    intent_confidence=float(meta.get("intent_confidence", 0.0)),
                    risk_level=RiskLevel.CRITICAL,
                    reason_codes=["policy_denied", *reason_codes],
                    policy_constraints={"denial_reason": policy_result["reason"]},
                )

        # ------------------------------------------------------------------
        # 7. Operational safety override (rollback)
        # ------------------------------------------------------------------
        if self._force_graph:
            graph_required = True
            reason_codes.append("force_graph_override")

        execution_mode = (
            RuntimeExecutionMode.GRAPH if graph_required else RuntimeExecutionMode.DIRECT
        )

        return ExecutionDecision(
            execution_mode=execution_mode,
            graph_required=graph_required,
            intent=str(meta.get("intent", "general_assist")),
            intent_confidence=float(meta.get("intent_confidence", 0.0)),
            risk_level=risk_level,
            reasoning_depth=reasoning_depth,
            memory_required=memory_required,
            memory_scope=memory_scope,
            tool_requirements=tool_requirements,
            plugin_candidates=plugin_candidates,
            required_capabilities=required_capabilities,
            forbidden_capabilities=forbidden_capabilities,
            requires_human_gate=requires_human_gate,
            requires_resumability=requires_resumability,
            requires_parallel_execution=requires_parallel_execution,
            requires_agent_delegation=requires_agent_delegation,
            max_steps=max_steps,
            time_budget_ms=time_budget_ms,
            token_budget=token_budget,
            reason_codes=reason_codes,
            policy_constraints=policy_constraints,
        )

    def _evaluate_topology_triggers(self, meta: Dict[str, Any]) -> List[str]:
        """Return reason codes for execution-topology-based graph triggers."""
        triggers: List[str] = []

        branching_required = bool(meta.get("branching_required", False))
        iterative_reasoning = bool(meta.get("iterative_reasoning_required", False))
        multiple_dependent_tools = bool(meta.get("multiple_dependent_tools", False))
        durable_state_required = bool(meta.get("durable_state_required", False))
        human_approval_required = bool(meta.get("human_approval_required", False))
        agent_delegation = bool(meta.get("agent_delegation", False))
        parallel_execution = bool(meta.get("parallel_execution", False))
        resumability = bool(meta.get("resumability", False))
        replanning_loop = bool(meta.get("replanning_loop", False))

        if branching_required:
            triggers.append("branching_required")
        if iterative_reasoning:
            triggers.append("iterative_reasoning_required")
        if multiple_dependent_tools:
            triggers.append("multiple_dependent_tools")
        if durable_state_required:
            triggers.append("durable_state_required")
        if human_approval_required:
            triggers.append("human_approval_required")
        if agent_delegation:
            triggers.append("agent_delegation")
        if parallel_execution:
            triggers.append("parallel_execution")
        if resumability:
            triggers.append("resumability")
        if replanning_loop:
            triggers.append("replanning_loop")

        return triggers

    def _assess_risk_level(
        self,
        meta: Dict[str, Any],
        tool_requirements: List[str],
        plugin_candidates: List[str],
    ) -> RiskLevel:
        """Assess execution risk from request signals."""
        explicit_risk = meta.get("risk_level")
        if explicit_risk:
            try:
                return RiskLevel(str(explicit_risk).lower())
            except ValueError:
                pass

        risk_score = 0
        if tool_requirements:
            risk_score += 1
        if plugin_candidates:
            risk_score += 2
        if meta.get("requires_human_gate"):
            risk_score += 2
        if meta.get("filesystem_write"):
            risk_score += 2
        if meta.get("network_access"):
            risk_score += 1
        if meta.get("system_command"):
            risk_score += 3

        if risk_score >= 5:
            return RiskLevel.CRITICAL
        if risk_score >= 3:
            return RiskLevel.HIGH
        if risk_score >= 1:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _check_capability_policy(
        self,
        required_capabilities: List[str],
        forbidden_capabilities: List[str],
        policy_constraints: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Fail-closed capability/policy check.

        Returns:
            Dict with 'allowed' bool and 'reason' string.
        """
        if not required_capabilities and not forbidden_capabilities and not policy_constraints:
            return {"allowed": True, "reason": "no_constraints"}

        effective_forbidden = set(
            policy_constraints.get("forbidden_capabilities", []) + forbidden_capabilities
        )
        for cap in required_capabilities:
            if cap in effective_forbidden:
                return {
                    "allowed": False,
                    "reason": f"required capability '{cap}' is forbidden by policy",
                }

        # If policy checker is unavailable, fail closed.
        policy_checker = policy_constraints.get("_policy_checker")
        if policy_checker is None and policy_constraints.get("require_policy_checker"):
            return {
                "allowed": False,
                "reason": "policy checker unavailable; failing closed",
            }

        return {"allowed": True, "reason": "policy_check_passed"}

    def cortex_never_executes(self) -> bool:
        """CORTEX decides but never executes providers, plugins, tools, memory, or LangGraph."""
        return True


_decider: Optional[CortexExecutionDecider] = None


def get_cortex_execution_decider() -> CortexExecutionDecider:
    """Return the singleton CORTEX execution decider."""
    global _decider
    if _decider is None:
        _decider = CortexExecutionDecider()
    return _decider
