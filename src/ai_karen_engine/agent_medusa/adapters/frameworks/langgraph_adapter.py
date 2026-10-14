"""
Medusa LangGraph adapter.

This adapter integrates Medusa specialists into LangGraph workflows,
routing specialist execution through the canonical GenerationBridge and
ToolBridge while respecting the AuthorizedExecutionPlan.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ...contracts.runtime_request import RuntimeRequest
from ...contracts.runtime_response import RuntimeResponse

logger = logging.getLogger(__name__)


class MedusaLangGraphAdapter:
    """Adapter for executing Medusa specialists within LangGraph workflows."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    async def execute_specialist(
        self,
        request: RuntimeRequest,
        plan: AuthorizedExecutionPlan,
        specialist_id: str,
        input_data: Dict[str, Any],
    ) -> RuntimeResponse:
        """Route a specialist-constrained LangGraph request through Medusa.

        LangGraph may express graph structure, but it must not execute a
        specialist outside RuntimePolicy, the canonical run manager, or Medusa's
        execution-time readiness gates.
        """
        from ...coordinator.medusa_coordinator import MedusaCoordinator
        from ai_karen_engine.core.runtime.workflow_runtime import _serialize_plan

        if not request.execution_requirements:
            raise PermissionError(
                "LangGraph specialist execution requires CORTEX requirements"
            )
        if request.authorized_plan is None:
            raise PermissionError(
                "LangGraph specialist execution requires RuntimePolicy authorization"
            )
        if request.authorized_plan.get("policy_decision_id") != plan.policy_decision_id:
            raise PermissionError("LangGraph Medusa policy decision mismatch")
        if not plan.matches_execution_scope(
            user_id=str(request.user_id or "").strip(),
            tenant_id=str(request.tenant_id or "").strip(),
            session_id=request.session_id,
            policy_decision_id=plan.policy_decision_id,
        ):
            raise PermissionError("LangGraph Medusa execution scope mismatch")
        if getattr(plan.topology, "value", plan.topology) != "multi_agent":
            raise PermissionError("LangGraph Medusa requires multi-agent topology")
        if (
            "*" not in set(plan.allowed_agents)
            and specialist_id not in set(plan.allowed_agents)
        ):
            raise PermissionError(
                "LangGraph specialist is not authorized by RuntimePolicy"
            )

        scoped_plan = replace(plan, allowed_agents=[specialist_id])
        scoped_context = dict(request.context)
        scoped_context["langgraph_specialist_input"] = dict(input_data)
        governed_request = replace(
            request,
            context=scoped_context,
            authorized_plan=_serialize_plan(scoped_plan),
        )
        return await MedusaCoordinator().handle_request(governed_request)

    async def execute_plan(
        self, request: RuntimeRequest, plan: AuthorizedExecutionPlan
    ) -> RuntimeResponse:
        """Delegate whole-plan execution to Medusa's canonical coordinator.

        This adapter must not schedule plan steps or execute specialists itself.
        The existing CORTEX requirements and RuntimePolicy plan remain required;
        no authorization is synthesized at the framework boundary.
        """
        from ...coordinator.medusa_coordinator import MedusaCoordinator
        from ai_karen_engine.core.runtime.workflow_runtime import _serialize_plan

        if not request.execution_requirements:
            raise PermissionError(
                "LangGraph Medusa plan execution requires CORTEX requirements"
            )
        if request.authorized_plan is None:
            raise PermissionError(
                "LangGraph Medusa plan execution requires RuntimePolicy authorization"
            )
        if request.authorized_plan.get("policy_decision_id") != plan.policy_decision_id:
            raise PermissionError("LangGraph Medusa policy decision mismatch")
        if not plan.matches_execution_scope(
            user_id=str(request.user_id or ""),
            tenant_id=str(request.tenant_id or ""),
            session_id=request.session_id,
            policy_decision_id=plan.policy_decision_id,
        ):
            raise PermissionError("LangGraph Medusa execution scope mismatch")
        if getattr(plan.topology, "value", plan.topology) != "multi_agent":
            raise PermissionError("LangGraph Medusa requires multi-agent topology")

        # Use the actual RuntimePolicy plan passed by the caller, not a
        # framework-local tool list or a reconstructed step graph.
        governed_request = replace(request, authorized_plan=_serialize_plan(plan))
        return await MedusaCoordinator().handle_request(governed_request)
