"""
Runtime policy for LangGraph orchestration.

Global policy enforcement (``RuntimePolicyEnforcer``, ``RuntimeLevel``, etc.)
lives in ``core.runtime.policy``. This module re-exports those primitives for
backward compatibility and adds LangGraph-specific node functions that apply
the global policy inside graph workflows.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ai_karen_engine.core.runtime.policy.runtime_policy import (
    PolicyCheckResult,
    RuntimeLevel,
    RuntimePolicyConfig,
    RuntimePolicyEnforcer,
)

logger = logging.getLogger(__name__)


async def runtime_policy_enforcer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Runtime policy enforcement node for LangGraph orchestration."""
    logger.info("Runtime policy enforcement processing")

    try:
        policy_enforcer = RuntimePolicyEnforcer()
        state = policy_enforcer.apply_runtime_constraints(state)

        if "provider_selection" in state:
            routing_check = await policy_enforcer.check_routing_policy(
                state, state["provider_selection"]
            )
            if not routing_check.allowed:
                state.setdefault("errors", []).append(
                    f"Routing blocked: {routing_check.reason}"
                )
                state["routing_blocked"] = True

        if "execution_plan" in state:
            execution_check = await policy_enforcer.check_execution_policy(
                state, state["execution_plan"]
            )
            if not execution_check.allowed:
                state.setdefault("errors", []).append(
                    f"Execution blocked: {execution_check.reason}"
                )
                state["execution_blocked"] = True

        if "llm_response" in state:
            response_check = await policy_enforcer.check_response_policy(
                state, state["llm_response"]
            )
            if not response_check.allowed:
                state.setdefault("errors", []).append(
                    f"Response blocked: {response_check.reason}"
                )
                state["response_blocked"] = True

        logger.info("Runtime policy enforcement completed")

    except Exception as e:
        logger.error(f"Runtime policy enforcement error: {e}")
        state.setdefault("errors", []).append(f"Runtime policy error: {str(e)}")

    return state


def select_execution_branch(state: Dict[str, Any]) -> str:
    """Select the execution branch for the LangGraph chat turn."""
    intent = str(state.get("detected_intent") or "").strip()
    request_config = state.get("request_config") or {}

    if isinstance(request_config, dict) and request_config.get("use_medusa"):
        return "medusa"

    if intent in (
        "admin_panel",
        "extension.action",
        "agent_complex_reasoning",
    ):
        return "medusa"

    return "normal"


def should_use_medusa(state: Dict[str, Any]) -> str:
    """Determine if AgentMedusa should handle the request."""
    intent = state.get("detected_intent", "")
    if intent in (
        "admin_panel",
        "extension.action",
        "agent_complex_reasoning",
    ):
        return "medusa"

    if state.get("request_config", {}).get("use_medusa"):
        return "medusa"

    return "normal"


def should_continue_after_auth(state: Dict[str, Any]) -> str:
    auth_status = state.get("auth_status")
    return "continue" if auth_status == "authenticated" else "reject"


def should_continue_after_safety(state: Dict[str, Any]) -> str:
    safety_status = state.get("safety_status")
    if safety_status == "safe":
        return "continue"
    elif safety_status == "review_required":
        return "review"
    else:
        return "reject"


def should_require_approval(state: Dict[str, Any]) -> str:
    safety_flags = state.get("safety_flags", [])
    tool_results = state.get("tool_results", [])

    if safety_flags or any("sensitive" in str(result) for result in tool_results):
        state["requires_approval"] = True
        return "review"
    else:
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
