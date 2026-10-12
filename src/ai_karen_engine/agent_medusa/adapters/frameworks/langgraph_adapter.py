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
from ...contracts.runtime_response import RuntimeResponse, ResponseStatus
from ...contracts.specialist_execution import SpecialistExecutionContext
from ...specialists.bridges import GenerationBridge, ToolBridge
from ...registry import get_medusa_registry
from ...registry_factory import get_implementation_factory

logger = logging.getLogger(__name__)


class MedusaLangGraphAdapter:
    """Adapter for executing Medusa specialists within LangGraph workflows."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._registry = get_medusa_registry()
        self._factory = get_implementation_factory()
        self._generation_bridge: Optional[GenerationBridge] = None
        self._tool_bridge: Optional[ToolBridge] = None

    async def execute_specialist(
        self,
        request: RuntimeRequest,
        plan: AuthorizedExecutionPlan,
        specialist_id: str,
        input_data: Dict[str, Any],
    ) -> RuntimeResponse:
        """Execute a single Medusa specialist within a LangGraph node."""
        registration = await self._registry.get_agent(specialist_id)
        if registration is None:
            return RuntimeResponse(
                request_id=request.request_id,
                status=ResponseStatus.ERROR,
                content=f"Specialist {specialist_id} not found",
                metadata={"error": "specialist_not_found"},
            )

        specialist = self._factory.resolve(registration)
        if specialist is None:
            return RuntimeResponse(
                request_id=request.request_id,
                status=ResponseStatus.ERROR,
                content=f"Specialist {specialist_id} could not be resolved",
                metadata={"error": "specialist_resolution_failed"},
            )

        from ai_karen_engine.core.runtime.contracts import ExecutionBudgetMeter
        meter = ExecutionBudgetMeter(plan.budget)
        meter.start()

        execution = SpecialistExecutionContext(
            authorized_plan=plan,
            tenant_id=getattr(request, "tenant_id", "default"),
            user_id=request.user_id or "anonymous",
            policy_decision_id=plan.policy_decision_id,
            trajectory_id=request.request_id,
            correlation_id=request.request_id,
            step_id=f"langgraph_{specialist_id}",
            budget_meter=meter,
        )

        context = {
            "session_id": request.session_id,
            "request_id": request.request_id,
            "previous_steps": {},
        }

        try:
            result = await specialist.run(input_data, context, execution=execution)
            return RuntimeResponse(
                request_id=request.request_id,
                status=ResponseStatus.SUCCESS,
                content=result.get("content") or result.get("response") or str(result),
                metadata={"specialist": specialist_id, "result": result},
            )
        except Exception as exc:
            logger.error(f"Specialist {specialist_id} execution failed: {exc}")
            return RuntimeResponse(
                request_id=request.request_id,
                status=ResponseStatus.ERROR,
                content=str(exc),
                metadata={"error": str(exc), "specialist": specialist_id},
            )

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
