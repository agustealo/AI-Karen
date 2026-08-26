"""Runtime authorization adapter for LangGraph workflows.

Global authorization is owned by ``core.runtime.policy`` and Runtime. LangGraph
receives an already-authorized plan and may only validate/consume it. This module
keeps legacy policy exports for import compatibility but graph nodes must not run a
second policy decision path.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from ai_karen_engine.core.runtime.policy.runtime_policy import (
    PolicyCheckResult,
    RuntimeLevel,
    RuntimePolicyConfig,
    RuntimePolicyEnforcer,
)

logger = logging.getLogger(__name__)

_ALLOWED_GRAPH_TOPOLOGIES = {"workflow", "multi_agent"}


def _runtime_plan(state: Dict[str, Any]) -> Dict[str, Any]:
    plan = state.get("runtime_policy")
    if not isinstance(plan, dict):
        raise PermissionError(
            "LangGraph execution requires AuthorizedExecutionPlan from RuntimePolicy"
        )
    if not str(plan.get("policy_decision_id") or "").strip():
        raise PermissionError(
            "LangGraph authorization requires a policy_decision_id"
        )
    topology = str(plan.get("topology") or "").strip().lower()
    if topology not in _ALLOWED_GRAPH_TOPOLOGIES:
        raise PermissionError(
            f"LangGraph execution is not authorized for topology '{topology or 'missing'}'"
        )
    return plan


async def runtime_policy_enforcer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the Runtime-provided authorization and fail closed if invalid.

    The historical implementation instantiated ``RuntimePolicyEnforcer`` inside the
    graph and re-evaluated routing/execution. That made LangGraph a second policy
    authority. Runtime now performs policy evaluation before entering WorkflowRuntime;
    this node only verifies that the downstream workflow still carries that decision.
    """
    plan = _runtime_plan(state)
    request_config = state.get("request_config") or {}
    expected_policy_id = (
        str(request_config.get("policy_decision_id") or "")
        if isinstance(request_config, dict)
        else ""
    )
    if expected_policy_id and expected_policy_id != str(plan["policy_decision_id"]):
        raise PermissionError(
            "LangGraph policy_decision_id does not match Runtime authorization"
        )

    state["policy_decision_id"] = str(plan["policy_decision_id"])
    state["execution_topology"] = str(plan["topology"])
    logger.info(
        "langgraph.runtime_authorization_validated",
        extra={
            "correlation_id": state.get("correlation_id"),
            "policy_decision_id": state["policy_decision_id"],
            "execution_topology": state["execution_topology"],
        },
    )
    return state


def select_execution_branch(state: Dict[str, Any]) -> str:
    """Select an execution branch from Runtime's authorized topology only."""
    plan = _runtime_plan(state)
    return "medusa" if str(plan["topology"]).lower() == "multi_agent" else "normal"


def should_use_medusa(state: Dict[str, Any]) -> str:
    """Compatibility alias for topology-authorized AgentMedusa selection."""
    return select_execution_branch(state)


def should_continue_after_auth(state: Dict[str, Any]) -> str:
    auth_status = state.get("auth_status")
    return "continue" if auth_status == "authenticated" else "reject"


def should_continue_after_safety(state: Dict[str, Any]) -> str:
    safety_status = state.get("safety_status")
    if safety_status == "safe":
        return "continue"
    if safety_status == "review_required":
        return "review"
    return "reject"


def should_require_approval(state: Dict[str, Any]) -> str:
    safety_flags = state.get("safety_flags", [])
    tool_results = state.get("tool_results", [])

    if safety_flags or any("sensitive" in str(result) for result in tool_results):
        state["requires_approval"] = True
        return "review"
    return "approve"


def check_approval_status(state: Dict[str, Any]) -> str:
    return state.get("approval_status", "pending")


__all__ = [
    "PolicyCheckResult",
    "RuntimeLevel",
    "RuntimePolicyConfig",
    "RuntimePolicyEnforcer",
    "runtime_policy_enforcer_node",
    "select_execution_branch",
    "should_use_medusa",
    "should_continue_after_auth",
    "should_continue_after_safety",
    "should_require_approval",
    "check_approval_status",
]
