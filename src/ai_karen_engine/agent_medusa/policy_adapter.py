"""Interim policy adapter for Medusa execution inputs.

AGENT-LIVE-1 wiring seam (A19). CORTEX decides topology and RuntimePolicy
issues the AuthorizedExecutionPlan. Until that integration lands, this adapter
synthesizes the required `ExecutionRequirements` + `AuthorizedExecutionPlan`
from the registry so Medusa can plan among registered, active agents.

Medusa MUST NOT re-decide topology or authorization here; it only consumes
what this adapter produces. Replace this with the real RuntimePolicy call.
"""

from __future__ import annotations

from typing import Any, Tuple

from ..core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionRequirements,
    ExecutionTopology,
)
from .contracts.agent_definition import AgentLifecycleState


async def build_execution_inputs(
    request: Any, registry: Any
) -> Tuple[ExecutionRequirements, AuthorizedExecutionPlan]:
    agents = await registry.list_agents()
    active_ids = [
        a.agent_id
        for a in agents
        if getattr(a, "lifecycle_state", AgentLifecycleState.ACTIVE) == AgentLifecycleState.ACTIVE
    ]
    allowed_agents = active_ids or ["*"]

    allowed_tools = list(request.context.get("allowed_tools", [])) or ["web_search"]

    requirements = ExecutionRequirements(
        request_id=request.request_id,
        correlation_id=request.request_id,
        intent="agent.multi_agent",
        requires_agent_delegation=True,
        topology_signals={"preferred": "multi_agent"},
    )

    authorized_plan = AuthorizedExecutionPlan(
        execution_id=request.request_id,
        policy_decision_id=f"medusa-{request.request_id}",
        topology=ExecutionTopology.MULTI_AGENT,
        allowed_agents=allowed_agents,
        allowed_tools=allowed_tools,
        allowed_plugins=[],
        budget=ExecutionBudget(),
        memory_scope="session",
    )
    return requirements, authorized_plan
