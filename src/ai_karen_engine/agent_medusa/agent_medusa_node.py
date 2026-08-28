from __future__ import annotations

import logging
from typing import Any, Dict

from ai_karen_engine.core.runtime.contracts import ExecutionContext

from .contracts.runtime_request import RuntimeRequest
from .coordinator.medusa_coordinator import MedusaCoordinator

logger = logging.getLogger(__name__)


def _require_state_identity(
    state: Dict[str, Any],
    primary: str,
    fallback: str | None = None,
) -> str:
    """Return one explicit scoped identity without inventing sentinel values."""

    raw = state.get(primary)
    if raw is None and fallback is not None:
        raw = state.get(fallback)
    value = str(raw or "").strip()
    if not value:
        raise ValueError(f"Medusa LangGraph state requires {primary}")
    return value


def _build_execution_context(
    state: Dict[str, Any], plan: Dict[str, Any]
) -> ExecutionContext:
    request_id = _require_state_identity(state, "request_id", "correlation_id")
    correlation_id = _require_state_identity(state, "correlation_id", "request_id")
    tenant_id = _require_state_identity(state, "tenant_id")

    return ExecutionContext(
        request_id=request_id,
        correlation_id=correlation_id,
        user_id=str(state.get("user_id") or "anonymous"),
        tenant_id=tenant_id,
        session_id=state.get("session_id"),
        conversation_id=state.get("conversation_id"),
        policy_decision_id=plan.get("policy_decision_id"),
        allowed_capabilities=plan.get("allowed_capabilities", []),
        resource_scope=plan.get("resource_scope", {}),
        budget=plan.get("budget"),
        audit_context=plan.get("audit_context", {}),
    )


async def medusa_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """LangGraph node that delegates authorized multi-agent execution to Medusa."""

    logger.info("Medusa Node -> Entering AgentMedusa execution")
    policy_decision = state.get("runtime_policy")
    if policy_decision is None or not isinstance(policy_decision, dict):
        raise ValueError("Medusa execution requires AuthorizedExecutionPlan in state")
    if policy_decision.get("topology") != "multi_agent":
        raise PermissionError("Medusa execution blocked by runtime policy decision")

    query = ""
    messages = state.get("messages", [])
    if messages:
        query = (
            messages[-1].content
            if hasattr(messages[-1], "content")
            else str(messages[-1])
        )

    execution_context = _build_execution_context(state, policy_decision)
    request = RuntimeRequest(
        query=query,
        session_id=str(state.get("session_id") or ""),
        request_id=execution_context.request_id,
        user_id=state.get("user_id"),
        tenant_id=execution_context.tenant_id,
        authorized_plan=policy_decision,
        execution_requirements=state.get("execution_requirements"),
        context={
            "tenant_id": execution_context.tenant_id,
            "execution_context": execution_context,
            "memory_context": state.get("memory_context", {}),
            "allowed_tools": policy_decision.get("allowed_tools", []),
            "allowed_plugins": policy_decision.get("allowed_plugins", []),
            "allowed_agents": policy_decision.get("allowed_agents", []),
        },
    )

    coordinator = MedusaCoordinator()
    response = await coordinator.handle_request(request)

    state["response"] = response.content
    state["response_metadata"] = response.metadata
    state["agent_trace"] = response.agent_trace
    state["medusa_status"] = response.status.value

    return state
