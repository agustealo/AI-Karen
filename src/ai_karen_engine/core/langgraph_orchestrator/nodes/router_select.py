"""Compatibility checkpoint before execution branching.

Provider/model selection is a Runtime responsibility. This node intentionally
performs no provider discovery, preference resolution, routing, or fallback.
It remains in the graph only to preserve the current node/edge topology while
provider authority is converged behind Runtime-owned execution ports.
"""

from __future__ import annotations

import logging
from typing import Any

from ..contracts.orchestration_state import LangGraphOrchestrationState

logger = logging.getLogger(__name__)


class RouterSelectNode:
    """Validate Runtime authorization without selecting a provider or model."""

    def __init__(self, llm_router: Any = None, profile_manager: Any = None) -> None:
        # Compatibility-only constructor arguments. LangGraph must not consume
        # either dependency for provider/model selection.
        self._compat_llm_router = llm_router
        self._compat_profile_manager = profile_manager

    async def __call__(
        self,
        state: LangGraphOrchestrationState,
    ) -> LangGraphOrchestrationState:
        logger.info("Runtime execution checkpoint processing")

        runtime_policy = state.get("runtime_policy")
        if not isinstance(runtime_policy, dict):
            raise PermissionError(
                "Workflow execution requires AuthorizedExecutionPlan from RuntimePolicy"
            )
        if not runtime_policy.get("policy_decision_id"):
            raise PermissionError(
                "Workflow execution authorization is missing policy_decision_id"
            )

        # Remove legacy provider-selection residue. Actual provider/model truth is
        # written only after Runtime executes the workflow generation request.
        state["route_decision"] = None
        state["selected_provider"] = None
        state["selected_model"] = None
        state["routing_reason"] = "Provider selection delegated to Runtime"
        return state


async def router_select_node(
    state: LangGraphOrchestrationState,
    llm_router: Any = None,
    profile_manager: Any = None,
) -> LangGraphOrchestrationState:
    """Compatibility wrapper for the Runtime execution checkpoint."""

    node = RouterSelectNode(llm_router=llm_router, profile_manager=profile_manager)
    return await node(state)
