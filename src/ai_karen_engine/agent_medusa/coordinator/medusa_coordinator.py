from typing import Any, Dict, List, Optional
import asyncio
import logging

from ..contracts.runtime_request import RuntimeRequest
from ..contracts.runtime_response import RuntimeResponse
from ..contracts.deep_execution_plan import DeepExecutionPlan, PlanStep, StepStatus
from ..planning.capability_planner import CapabilityAwareMedusaPlanner
from ..registry import get_medusa_registry
from ..registry_factory import get_implementation_factory
from ..response.assembler import ResponseAssembler
from ..lifecycle.lifecycle_manager import MedusaAgentLifecycle, LifecycleStatus
from ..contracts.safe_error import to_safe_response
from ..execution.failure_policy import aggregate_status
from ..contracts.specialist_execution import SpecialistExecutionContext
from ..execution.event_emitter import EventEmitter
from ..contracts.trace import ExecutionTrajectory
from ..contracts.events import AgentEvent, AgentEventType
from ..adapters.extension_runtime_adapter import ExtensionRuntimeAdapter
from ..adapters.memory_runtime_adapter import MemoryRuntimeAdapter
from ...core.runtime.contracts import (
    ExecutionBudget,
    ExecutionRequirements,
    AuthorizedExecutionPlan,
)

logger = logging.getLogger(__name__)


class MedusaCoordinator:
    """The central orchestration authority for the AgentMedusa runtime layer.

    Medusa is a multi-agent execution topology coordinator only. It:
    - plans among capabilities RuntimePolicy already authorized (no re-decision)
    - resolves specialists through the canonical registry/factory (no hardcoded map)
    - routes model work through GenerationBridge + ProviderRouter
    - routes tool side effects through ActionExecutionGate
    - synthesizes real results via ResponseAssembler (no canned strings)
    - returns safe errors (no raw exception exposure)
    """

    def __init__(
        self,
        planner: Optional[CapabilityAwareMedusaPlanner] = None,
        registry: Any = None,
        factory: Any = None,
        assembler: Optional[ResponseAssembler] = None,
        lifecycle: Optional[MedusaAgentLifecycle] = None,
        event_emitter: Optional[EventEmitter] = None,
    ):
        self.planner = planner or CapabilityAwareMedusaPlanner()
        self.registry = registry or get_medusa_registry()
        self.factory = factory or get_implementation_factory()
        self.assembler = assembler or ResponseAssembler()
        self.lifecycle = lifecycle or MedusaAgentLifecycle()
        self.active_plans: Dict[str, DeepExecutionPlan] = {}
        self.event_emitter = event_emitter or EventEmitter()
        self.trajectories: Dict[str, ExecutionTrajectory] = {}
        self.extension_adapter = ExtensionRuntimeAdapter()
        self.memory_adapter = MemoryRuntimeAdapter()
        self._global_sinks: List[Any] = []

    def attach_sink(self, sink: Any) -> None:
        """Attach a durable event sink (e.g. websocket stream) to all runs."""
        self._global_sinks.append(sink)
        self.event_emitter._sinks.append(sink)

    async def handle_request(self, request: RuntimeRequest) -> RuntimeResponse:
        logger.info(f"Medusa Coordinator -> Handling request {request.request_id}")
        try:
            if request.authorized_plan is not None:
                plan_data = dict(request.authorized_plan)
                budget_data = plan_data.pop("budget", None)
                if isinstance(budget_data, dict):
                    budget_data = ExecutionBudget(**budget_data)
                plan_data["budget"] = budget_data
                authorized_plan = AuthorizedExecutionPlan(**plan_data)
                if request.execution_requirements is not None:
                    requirements = ExecutionRequirements(**request.execution_requirements)
                else:
                    requirements = ExecutionRequirements(
                        request_id=request.request_id,
                        correlation_id=request.request_id,
                        intent="agent.multi_agent",
                        requires_agent_delegation=True,
                        topology_signals={"preferred": "multi_agent"},
                    )
            else:
                from ..policy_adapter import build_execution_inputs
                requirements, authorized_plan = await build_execution_inputs(request, self.registry)

            plan = await self.planner.create_plan(
                request_id=request.request_id,
                query=request.query,
                requirements=requirements,
                authorized_plan=authorized_plan,
                registry=self.registry,
                budget=authorized_plan.budget,
                context=request.context,
            )

            from ...core.runtime.contracts import ExecutionBudgetMeter
            meter = ExecutionBudgetMeter(authorized_plan.budget)
            meter.start()

            trajectory = ExecutionTrajectory(request_id=request.request_id, trajectory_id=request.request_id)
            request_emitter = EventEmitter(sinks=list(self._global_sinks))
            self.active_plans[request.request_id] = plan
            try:
                step_outputs: list[Dict[str, Any]] = []
                agent_trace: list[str] = []
                while not plan.is_complete:
                    # A17: stop scheduling once the authorized budget is exhausted.
                    if meter.exhausted:
                        for s in plan.steps:
                            if s.status == StepStatus.PENDING:
                                s.status = StepStatus.SKIPPED
                        plan.is_complete = True
                        break
                    runnable_steps = plan.get_next_runnable_steps()
                    if not runnable_steps:
                        if all(s.status == StepStatus.COMPLETED for s in plan.steps):
                            plan.is_complete = True
                            break
                        raise RuntimeError("Medusa Execution Stalled: dependency failure")
                    results = await asyncio.gather(
                        *[
                            self._execute_step(step, plan, request, authorized_plan, meter, request_emitter, trajectory)
                            for step in runnable_steps
                        ],
                        return_exceptions=True,
                    )
                    for step, res in zip(runnable_steps, results):
                        if isinstance(res, Exception):
                            step.status = StepStatus.FAILED
                            step.error = str(res)
                        else:
                            step_outputs.append(res)
                            agent_trace.append(step.agent_specialist)
            finally:
                # Cleanup in-memory active plan after durable handling (A15).
                self.active_plans.pop(request.request_id, None)

            final_status = aggregate_status([s.status.value for s in plan.steps])
            trajectory.complete(final_status.value)
            trajectory.events = request_emitter._events
            self.trajectories[request.request_id] = trajectory
            return await self.assembler.assemble(
                request_id=request.request_id,
                step_outputs=step_outputs,
                agent_trace=agent_trace,
                latest_user_message=request.query,
                status=final_status,
                metadata={"plan": plan.to_dict(), "trajectory": trajectory.to_dict()},
            )
        except Exception as e:
            return to_safe_response(e, correlation_id=request.request_id)

    async def _execute_step(
        self,
        step: PlanStep,
        plan: DeepExecutionPlan,
        request: RuntimeRequest,
        authorized_plan: Any,
        meter: Any = None,
        emitter: Any = None,
        trajectory: Any = None,
    ) -> Dict[str, Any]:
        logger.info(f"Medusa Coordinator -> Executing Step: {step.description} via {step.agent_specialist}")
        step.status = StepStatus.RUNNING
        emitter = emitter or self.event_emitter

        # A18: an agent with unhealthy capability dependencies runs degraded.
        health = await self.registry.get_agent_health(step.agent_specialist)
        if health.get("exists") and not health.get("healthy"):
            await self.lifecycle.set_status(step.agent_specialist, LifecycleStatus.DEGRADED)

        registration = await self.registry.get_agent(step.agent_specialist)
        if registration is None:
            raise ValueError(f"Specialist {step.agent_specialist} not found in registry")

        specialist = self.factory.resolve(registration)

        if emitter is not None:
            await emitter.emit(AgentEvent(
                type=AgentEventType.AGENT_STARTED,
                agent_id=step.agent_specialist,
                message=f"step {step.id} started",
                correlation_id=request.request_id,
                metadata={"step_id": step.id},
            ))

        execution = SpecialistExecutionContext(
            authorized_plan=authorized_plan,
            tenant_id=getattr(request, "tenant_id", "default"),
            user_id=request.user_id or "anonymous",
            policy_decision_id=authorized_plan.policy_decision_id,
            trajectory_id=request.request_id,
            correlation_id=request.request_id,
            step_id=step.id,
            budget_meter=meter,
            event_emitter=emitter,
        )
        context = {
            "session_id": request.session_id,
            "request_id": request.request_id,
            "plan_metadata": plan.metadata,
            "previous_steps": {s.id: s.output_data for s in plan.steps if s.status == StepStatus.COMPLETED},
        }

        await self.lifecycle.set_status(step.agent_specialist, LifecycleStatus.BUSY)
        try:
            result = await specialist.run(step.input_data, context, execution=execution)
            step.status = StepStatus.COMPLETED
            step.output_data = result
            if emitter is not None:
                await emitter.emit(AgentEvent(
                    type=AgentEventType.AGENT_COMPLETED,
                    agent_id=step.agent_specialist,
                    message=f"step {step.id} completed",
                    correlation_id=request.request_id,
                    metadata={"step_id": step.id},
                ))
            if trajectory is not None:
                trajectory.record_step({"agent_id": step.agent_specialist, "step_id": step.id, "output": result})
            return result
        except Exception as exc:
            if emitter is not None:
                await emitter.emit(AgentEvent(
                    type=AgentEventType.AGENT_FAILED,
                    agent_id=step.agent_specialist,
                    message=f"step {step.id} failed: {exc}",
                    correlation_id=request.request_id,
                    metadata={"step_id": step.id, "error": str(exc)},
                ))
            raise
        finally:
            await self.lifecycle.set_status(step.agent_specialist, LifecycleStatus.IDLE)




