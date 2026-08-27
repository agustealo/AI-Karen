from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from ...core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionRequirements,
)
from ..adapters.extension_runtime_adapter import ExtensionRuntimeAdapter
from ..adapters.memory_runtime_adapter import MemoryRuntimeAdapter
from ..contracts.deep_execution_plan import (
    DeepExecutionPlan,
    DegradationLevel,
    DegradationMetadata,
    PlanStep,
    StepStatus,
)
from ..contracts.events import AgentEvent, AgentEventType
from ..contracts.runtime_request import RuntimeRequest
from ..contracts.runtime_response import RuntimeResponse
from ..contracts.safe_error import to_safe_response
from ..contracts.specialist_execution import SpecialistExecutionContext
from ..contracts.trace import ExecutionTrajectory
from ..execution.event_emitter import EventEmitter
from ..execution.failure_policy import aggregate_status
from ..execution.run_manager import MedusaRunManager, get_medusa_run_manager
from ..lifecycle.lifecycle_manager import LifecycleStatus, MedusaAgentLifecycle
from ..planning.capability_planner import CapabilityAwareMedusaPlanner
from ..registry import get_medusa_registry
from ..registry_factory import get_implementation_factory
from ..response.assembler import ResponseAssembler

logger = logging.getLogger(__name__)


class MedusaCoordinator:
    """Canonical multi-agent execution coordinator.

    RuntimePolicy authorizes the plan. Medusa coordinates execution only. The
    process-wide run manager owns observable request lifecycle and cancellation
    of the actual asyncio task. Per-agent lifecycle remains observational.
    """

    def __init__(
        self,
        planner: Optional[CapabilityAwareMedusaPlanner] = None,
        registry: Any = None,
        factory: Any = None,
        assembler: Optional[ResponseAssembler] = None,
        lifecycle: Optional[MedusaAgentLifecycle] = None,
        event_emitter: Optional[EventEmitter] = None,
        run_manager: Optional[MedusaRunManager] = None,
    ) -> None:
        self.planner = planner or CapabilityAwareMedusaPlanner()
        self.registry = registry or get_medusa_registry()
        self.factory = factory or get_implementation_factory()
        self.assembler = assembler or ResponseAssembler()
        self.lifecycle = lifecycle or MedusaAgentLifecycle()
        self.run_manager = run_manager or get_medusa_run_manager()
        self.active_plans: Dict[str, DeepExecutionPlan] = {}
        self.event_emitter = event_emitter or EventEmitter()
        self.trajectories: Dict[str, ExecutionTrajectory] = {}
        self.extension_adapter = ExtensionRuntimeAdapter()
        self.memory_adapter = MemoryRuntimeAdapter()
        self._global_sinks: List[Any] = []

    def attach_sink(self, sink: Any) -> None:
        """Attach a durable event sink to all runs."""

        self._global_sinks.append(sink)
        self.event_emitter._sinks.append(sink)

    async def handle_request(self, request: RuntimeRequest) -> RuntimeResponse:
        """Execute one authorized Medusa request with enforceable cancellation."""

        current_task = asyncio.current_task()
        if current_task is None:  # pragma: no cover - asyncio always supplies one here
            raise RuntimeError("Medusa execution requires an asyncio task")

        tenant_id = str(getattr(request, "tenant_id", None) or "default")
        user_id = str(request.user_id or "anonymous")
        await self.run_manager.register(
            run_id=request.request_id,
            correlation_id=request.request_id,
            tenant_id=tenant_id,
            user_id=user_id,
            task=current_task,
        )
        logger.info(
            "medusa_run_started",
            extra={
                "run_id": request.request_id,
                "correlation_id": request.request_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
            },
        )

        try:
            response = await self._handle_request(request)
        except asyncio.CancelledError:
            await self.run_manager.mark_cancelled(request.request_id)
            logger.info(
                "medusa_run_cancelled",
                extra={
                    "run_id": request.request_id,
                    "correlation_id": request.request_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                },
            )
            raise
        except Exception as exc:
            await self.run_manager.mark_failed(request.request_id, exc)
            logger.exception(
                "medusa_run_failed",
                extra={
                    "run_id": request.request_id,
                    "correlation_id": request.request_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "error_type": type(exc).__name__,
                },
            )
            return to_safe_response(exc, correlation_id=request.request_id)
        else:
            await self.run_manager.mark_completed(request.request_id)
            logger.info(
                "medusa_run_completed",
                extra={
                    "run_id": request.request_id,
                    "correlation_id": request.request_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                },
            )
            return response

    async def _handle_request(self, request: RuntimeRequest) -> RuntimeResponse:
        if request.authorized_plan is None:
            raise PermissionError(
                "MedusaCoordinator requires an authorized_plan from RuntimePolicy. "
                "Medusa must not synthesize its own authorization."
            )

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
        trajectory = ExecutionTrajectory(
            request_id=request.request_id,
            trajectory_id=request.request_id,
        )
        request_emitter = EventEmitter(sinks=list(self._global_sinks))
        self.active_plans[request.request_id] = plan
        degraded_agents: List[str] = []
        degradation_reasons: Dict[str, str] = {}
        step_outputs: list[Dict[str, Any]] = []
        agent_trace: list[str] = []

        try:
            while not plan.is_complete:
                if meter.exhausted:
                    for step in plan.steps:
                        if step.status == StepStatus.PENDING:
                            step.status = StepStatus.SKIPPED
                    plan.is_complete = True
                    break

                runnable_steps = plan.get_next_runnable_steps()
                if not runnable_steps:
                    if all(step.status == StepStatus.COMPLETED for step in plan.steps):
                        plan.is_complete = True
                        break
                    raise RuntimeError("Medusa Execution Stalled: dependency failure")

                results = await asyncio.gather(
                    *[
                        self._execute_step(
                            step,
                            plan,
                            request,
                            authorized_plan,
                            meter,
                            request_emitter,
                            trajectory,
                            degraded_agents,
                            degradation_reasons,
                        )
                        for step in runnable_steps
                    ],
                    return_exceptions=True,
                )
                for step, result in zip(runnable_steps, results):
                    if isinstance(result, BaseException):
                        step.status = StepStatus.FAILED
                        step.error = type(result).__name__
                    else:
                        step_outputs.append(result)
                        agent_trace.append(step.agent_specialist)
        finally:
            self.active_plans.pop(request.request_id, None)

        if degraded_agents:
            plan.degraded_mode = True
            plan.degradation_metadata = DegradationMetadata(
                degraded=True,
                degradation_reason=(
                    f"Agents {', '.join(degraded_agents)} ran in degraded mode"
                ),
                affected_agent=", ".join(degraded_agents),
                fallback_level=DegradationLevel.PARTIAL,
                capabilities_lost=degradation_reasons.get("capabilities_lost", []),
                original_requirement=degradation_reasons.get(
                    "original_requirement",
                    "full agent execution",
                ),
            )

        final_status = aggregate_status([step.status.value for step in plan.steps])
        trajectory.complete(final_status.value)
        trajectory.events = request_emitter._events
        self.trajectories[request.request_id] = trajectory
        response_metadata = {
            "plan": plan.to_dict(),
            "trajectory": trajectory.to_dict(),
            "execution_topology": "multi_agent",
            "policy_decision_id": authorized_plan.policy_decision_id,
        }
        if plan.degraded_mode and plan.degradation_metadata is not None:
            response_metadata["degraded_mode"] = True
            response_metadata["degradation_reason"] = (
                plan.degradation_metadata.degradation_reason
            )
            response_metadata["affected_agents"] = degraded_agents
            response_metadata["fallback_level"] = (
                plan.degradation_metadata.fallback_level.value
            )

        return await self.assembler.assemble(
            request_id=request.request_id,
            step_outputs=step_outputs,
            agent_trace=agent_trace,
            latest_user_message=request.query,
            status=final_status,
            metadata=response_metadata,
        )

    async def _execute_step(
        self,
        step: PlanStep,
        plan: DeepExecutionPlan,
        request: RuntimeRequest,
        authorized_plan: Any,
        meter: Any = None,
        emitter: Any = None,
        trajectory: Any = None,
        degraded_agents: Optional[List[str]] = None,
        degradation_reasons: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        logger.info(
            "medusa_step_started",
            extra={
                "run_id": request.request_id,
                "step_id": step.id,
                "agent_id": step.agent_specialist,
            },
        )
        step.status = StepStatus.RUNNING
        emitter = emitter or self.event_emitter
        health = await self.registry.get_agent_health(step.agent_specialist)
        is_degraded = bool(health.get("exists") and not health.get("healthy"))

        if is_degraded:
            await self.lifecycle.set_status(
                step.agent_specialist,
                LifecycleStatus.DEGRADED,
            )
            if degraded_agents is not None:
                degraded_agents.append(step.agent_specialist)
            if degradation_reasons is not None:
                degradation_reasons[step.agent_specialist] = health.get(
                    "degradation_reason",
                    "Agent unhealthy",
                )
            step.degradation_metadata = DegradationMetadata(
                degraded=True,
                degradation_reason=health.get(
                    "degradation_reason",
                    "Agent unhealthy",
                ),
                affected_agent=step.agent_specialist,
                fallback_level=DegradationLevel.PARTIAL,
                capabilities_lost=health.get("capabilities_lost", []),
            )

        registration = await self.registry.get_agent(step.agent_specialist)
        if registration is None:
            raise ValueError(f"Specialist {step.agent_specialist} not found in registry")
        specialist = self.factory.resolve(registration)

        if emitter is not None:
            await emitter.emit(
                AgentEvent(
                    type=AgentEventType.AGENT_STARTED,
                    agent_id=step.agent_specialist,
                    message=f"step {step.id} started",
                    correlation_id=request.request_id,
                    metadata={"step_id": step.id, "degraded": is_degraded},
                )
            )

        execution = SpecialistExecutionContext(
            authorized_plan=authorized_plan,
            tenant_id=str(getattr(request, "tenant_id", None) or "default"),
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
            "previous_steps": {
                previous.id: previous.output_data
                for previous in plan.steps
                if previous.status == StepStatus.COMPLETED
            },
            "degraded_mode": is_degraded,
        }

        await self.lifecycle.set_status(step.agent_specialist, LifecycleStatus.BUSY)
        try:
            result = await specialist.run(step.input_data, context, execution=execution)
            step.status = StepStatus.COMPLETED
            step.output_data = result
            if emitter is not None:
                await emitter.emit(
                    AgentEvent(
                        type=AgentEventType.AGENT_COMPLETED,
                        agent_id=step.agent_specialist,
                        message=f"step {step.id} completed",
                        correlation_id=request.request_id,
                        metadata={"step_id": step.id, "degraded": is_degraded},
                    )
                )
            if trajectory is not None:
                trajectory.record_step(
                    {
                        "agent_id": step.agent_specialist,
                        "step_id": step.id,
                        "output": result,
                        "degraded": is_degraded,
                    }
                )
            return result
        except asyncio.CancelledError:
            step.status = StepStatus.FAILED
            step.error = "cancelled"
            logger.info(
                "medusa_step_cancelled",
                extra={
                    "run_id": request.request_id,
                    "step_id": step.id,
                    "agent_id": step.agent_specialist,
                },
            )
            raise
        except Exception as exc:
            if emitter is not None:
                await emitter.emit(
                    AgentEvent(
                        type=AgentEventType.AGENT_FAILED,
                        agent_id=step.agent_specialist,
                        message=f"step {step.id} failed",
                        correlation_id=request.request_id,
                        metadata={
                            "step_id": step.id,
                            "error_type": type(exc).__name__,
                            "degraded": is_degraded,
                        },
                    )
                )
            raise
        finally:
            await self.lifecycle.set_status(step.agent_specialist, LifecycleStatus.IDLE)
