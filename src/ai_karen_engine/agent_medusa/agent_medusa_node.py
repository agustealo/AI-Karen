from typing import Dict, Any, List
import logging
from .coordinator.medusa_coordinator import MedusaCoordinator
from .contracts.runtime_request import RuntimeRequest
from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan, ExecutionContext

logger = logging.getLogger(__name__)


def _build_execution_context(state: Dict[str, Any], plan: AuthorizedExecutionPlan) -> ExecutionContext:
    return ExecutionContext(
        request_id=state.get("request_id", state.get("correlation_id", "unknown")),
        correlation_id=state.get("correlation_id", state.get("request_id", "unknown")),
        user_id=state.get("user_id", "anonymous"),
        tenant_id=state.get("tenant_id", "default"),
        session_id=state.get("session_id"),
        conversation_id=state.get("conversation_id"),
        policy_decision_id=plan.policy_decision_id,
        allowed_capabilities=plan.allowed_capabilities,
        resource_scope=plan.resource_scope,
        budget=plan.budget,
        audit_context=plan.audit_context,
    )


async def medusa_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """LangGraph node that delegates execution to the AgentMedusa runtime"""
    logger.info("Medusa Node -> Entering AgentMedusa execution")
    policy_decision = state.get("runtime_policy")
    if not isinstance(policy_decision, AuthorizedExecutionPlan):
        raise ValueError("Medusa execution requires AuthorizedExecutionPlan in state")
    if policy_decision.topology != "multi_agent":
        raise PermissionError("Medusa execution blocked by runtime policy decision")

    coordinator = MedusaCoordinator()

    query = ""
    messages = state.get("messages", [])
    if messages:
        query = messages[-1].content if hasattr(messages[-1], "content") else str(messages[-1])

    execution_context = _build_execution_context(state, policy_decision)
    request = RuntimeRequest(
        query=query,
        session_id=state.get("session_id", "unknown"),
        user_id=state.get("user_id"),
        context={
            "execution_context": execution_context,
            "memory_context": state.get("memory_context", {}),
            "allowed_tools": policy_decision.allowed_tools,
            "allowed_plugins": policy_decision.allowed_plugins,
            "allowed_agents": policy_decision.allowed_agents,
        },
    )

    response = await coordinator.handle_request(request)

    state["response"] = response.content
    state["response_metadata"] = response.metadata
    state["agent_trace"] = response.agent_trace
    state["medusa_status"] = response.status.value

    return state
