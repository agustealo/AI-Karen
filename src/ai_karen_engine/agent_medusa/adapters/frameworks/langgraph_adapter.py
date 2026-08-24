"""
Medusa LangGraph adapter.

This adapter integrates Medusa specialists into LangGraph workflows,
routing specialist execution through the canonical GenerationBridge and
ToolBridge while respecting the AuthorizedExecutionPlan.
"""

from __future__ import annotations

import logging
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
        """Execute all steps in an AuthorizedExecutionPlan sequentially."""
        from ..planning.deep_execution_plan import PlanStep, StepStatus

        steps: List[PlanStep] = []
        step_data = plan.agent_topology or {}
        if isinstance(step_data, list):
            for idx, step_def in enumerate(step_data):
                if isinstance(step_def, dict):
                    steps.append(
                        PlanStep(
                            id=step_def.get("id", f"step_{idx}"),
                            description=step_def.get("description", ""),
                            agent_specialist=step_def.get("specialist")
                    or step_def.get("agent_id"),
                            agent_version=step_def.get("version"),
                            input_data=step_def.get("input", {}),
                            dependencies=step_def.get("dependencies", []),
                            required_tools=list(plan.allowed_tools),
                            required_plugins=list(plan.allowed_plugins),
                        )
                    )
                elif isinstance(step_def, str):
                    steps.append(
                        PlanStep(
                            id=f"step_{idx}",
                            description=f"Execute {step_def}",
                            agent_specialist=step_def,
                            agent_version=None,
                            input_data={},
                            dependencies=[],
                            required_tools=list(plan.allowed_tools),
                            required_plugins=list(plan.allowed_plugins),
                        )
                    )

        if not steps:
            return RuntimeResponse(
                request_id=request.request_id,
                status=ResponseStatus.ERROR,
                content="No steps in execution plan",
                metadata={"error": "empty_plan"},
            )

        outputs: List[Dict[str, Any]] = []
        completed: Dict[str, Any] = {}
        for step in steps:
            input_data = dict(step.input_data)
            input_data.setdefault("query", request.query)
            input_data.setdefault("previous_steps", completed)

            response = await self.execute_specialist(
                request=request,
                plan=plan,
                specialist_id=step.agent_specialist,
                input_data=input_data,
            )
            if response.status == ResponseStatus.SUCCESS:
                step.status = StepStatus.COMPLETED
                step.output_data = {
                    "content": response.content,
                    "metadata": response.metadata,
                }
                completed[step.id] = step.output_data
                outputs.append(step.output_data)
            else:
                step.status = StepStatus.FAILED
                step.error = (
                    response.metadata.get("error")
                    if response.metadata
                    else "unknown"
                )
                break

        from ..response.assembler import ResponseAssembler
        assembler = ResponseAssembler()
        return await assembler.assemble(
            request_id=request.request_id,
            step_outputs=outputs,
            agent_trace=[
                s.agent_specialist
                for s in steps
                if s.status == StepStatus.COMPLETED
            ],
            latest_user_message=request.query,
            status=ResponseStatus.SUCCESS if outputs else ResponseStatus.ERROR,
            metadata={"plan_steps": len(steps), "completed_steps": len(outputs)},
        )
