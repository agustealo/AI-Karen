from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import Any, Dict, List, Optional

from ...core.runtime.outcome.store import OutcomeStoreError
from ...core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionRequirements,
)
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

        tenant_id = str(request.tenant_id or "").strip()
        user_id = str(request.user_id or "").strip()
        if not tenant_id:
            raise PermissionError("Medusa execution requires tenant identity")
        if not user_id:
            raise PermissionError("Medusa execution requires user identity")
        if not isinstance(request.execution_requirements, dict):
            raise PermissionError(
                "Medusa execution requires explicit CORTEX execution requirements"
            )
        requirements = ExecutionRequirements(**request.execution_requirements)
        if not requirements.requires_agent_delegation:
            raise PermissionError(
                "Medusa execution requires CORTEX-requested agent delegation"
            )
        if requirements.request_id != request.request_id:
            raise PermissionError("Medusa CORTEX request identity mismatch")
        execution_context = request.context.get("execution_context")
        expected_correlation_id = getattr(
            execution_context, "correlation_id", request.request_id
        )
        if requirements.correlation_id != expected_correlation_id:
            raise PermissionError("Medusa CORTEX correlation identity mismatch")

        plan_data = (
            request.authorized_plan if isinstance(request.authorized_plan, dict) else {}
        )
        if not plan_data:
            raise PermissionError("Medusa execution requires a RuntimePolicy plan")
        policy_decision_id_raw = plan_data.get("policy_decision_id")
        policy_decision_id = str(policy_decision_id_raw or "").strip()
        if not policy_decision_id:
            raise PermissionError(
                "Medusa execution requires RuntimePolicy decision identity"
            )
        if (
            str(plan_data.get("authorized_user_id") or "").strip() != user_id
            or str(plan_data.get("authorized_tenant_id") or "").strip() != tenant_id
        ):
            raise PermissionError("Medusa RuntimePolicy principal scope mismatch")
        authorized_session_id = plan_data.get("authorized_session_id")
        if (
            authorized_session_id is not None
            and str(authorized_session_id) != request.session_id
        ):
            raise PermissionError("Medusa RuntimePolicy session scope mismatch")
        plan_topology = plan_data.get("topology")
        if getattr(plan_topology, "value", plan_topology) != "multi_agent":
            raise PermissionError("Medusa RuntimePolicy topology must be multi_agent")
        await self.run_manager.register(
            run_id=request.request_id,
            correlation_id=requirements.correlation_id,
            request_id=request.request_id,
            session_id=request.session_id,
            policy_decision_id=policy_decision_id,
            tenant_id=tenant_id,
            user_id=user_id,
            task=current_task,
        )
        logger.info(
            "medusa_run_started",
            extra={
                "run_id": request.request_id,
                "correlation_id": requirements.correlation_id,
                "request_id": request.request_id,
                "session_id": request.session_id,
                "policy_decision_id": policy_decision_id,
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
                    "correlation_id": requirements.correlation_id,
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
                    "correlation_id": requirements.correlation_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "error_type": type(exc).__name__,
                },
            )
            return to_safe_response(exc, correlation_id=requirements.correlation_id)
        else:
            await self.run_manager.mark_response(
                request.request_id,
                response.status.value,
            )
            logger.info(
                "medusa_run_finished",
                extra={
                    "run_id": request.request_id,
                    "correlation_id": requirements.correlation_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "outcome_status": response.status.value,
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

        requirements = ExecutionRequirements(**request.execution_requirements)

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
        started_at_ms = asyncio.get_running_loop().time() * 1000
        trajectory = ExecutionTrajectory(
            request_id=request.request_id,
            trajectory_id=request.request_id,
        )
        request_emitter = EventEmitter(sinks=list(self._global_sinks))
        self.active_plans[request.request_id] = plan
        degraded_agents: List[str] = []
        degradation_reasons: Dict[str, Any] = {}
        step_outputs: list[Dict[str, Any]] = []
        agent_trace: list[str] = []

        try:
            while not plan.is_complete:
                if meter.exhausted or not await meter.check_duration():
                    for step in plan.steps:
                        if step.status == StepStatus.PENDING:
                            step.status = StepStatus.SKIPPED
                            step.error = "execution_budget_exhausted"
                    plan.is_complete = True
                    break

                plan.mark_blocked_dependents()
                runnable_steps = plan.get_next_runnable_steps()
                if not runnable_steps:
                    if all(
                        step.status
                        in {
                            StepStatus.COMPLETED,
                            StepStatus.FAILED,
                            StepStatus.SKIPPED,
                        }
                        for step in plan.steps
                    ):
                        plan.is_complete = True
                        break
                    raise RuntimeError(
                        "Medusa Execution Stalled: unresolved dependency graph"
                    )

                # The validated DAG can expose more runnable nodes than the
                # RuntimePolicy concurrency budget permits. Execute stable,
                # bounded waves without giving adapters scheduling authority.
                max_parallel = int(authorized_plan.budget.max_parallelism)
                if max_parallel < 1:
                    raise ValueError("Invalid Medusa parallelism budget")
                wave = runnable_steps[:max_parallel]
                # A duration check between waves does not interrupt a hung
                # specialist. Bound the running wave by the remaining request
                # deadline, and cancel unfinished child tasks on timeout.
                elapsed_ms = asyncio.get_running_loop().time() * 1000 - started_at_ms
                remaining_seconds = (
                    authorized_plan.budget.max_duration_ms - elapsed_ms
                ) / 1000
                if remaining_seconds <= 0:
                    for step in wave:
                        step.status = StepStatus.SKIPPED
                        step.error = "execution_budget_exhausted"
                    continue
                try:
                    async with asyncio.timeout(remaining_seconds):
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
                                for step in wave
                            ],
                            return_exceptions=True,
                        )
                except TimeoutError:
                    for step in wave:
                        if step.status != StepStatus.COMPLETED:
                            step.status = StepStatus.FAILED
                            step.error = "execution_deadline_exceeded"
                    for step in plan.steps:
                        if step.status == StepStatus.PENDING:
                            step.status = StepStatus.SKIPPED
                            step.error = "execution_budget_exhausted"
                    plan.is_complete = True
                    break
                # A tool may have changed external state even when its audit
                # receipt failed. Never downgrade that uncertainty to a
                # partial response merely because sibling agents succeeded.
                self._require_durable_tool_receipts(results)
                for step, result in zip(wave, results):
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
        response_metadata: Dict[str, Any] = {
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
        registration = await self.registry.get_agent(step.agent_specialist)
        if registration is None:
            raise ValueError(
                f"Specialist {step.agent_specialist} not found in registry"
            )

        health = await self.registry.get_agent_health(step.agent_specialist)
        dependency_verified = await self._dependencies_verified_by_completed_steps(
            step=step,
            plan=plan,
            unresolved=set(health.get("unknown_dependencies") or []),
        )
        explicitly_degraded = bool(
            authorized_plan.degraded_allowed
            and authorized_plan.degradation_state is not None
            and authorized_plan.degradation_state.degraded
        )
        # Explicit degradation never reactivates disabled/archived agents,
        # overrides missing registrations, or turns a known missing dependency
        # into a successfully fulfilled in-plan dependency.
        lifecycle_state = str(getattr(registration, "lifecycle_state", "")).lower()
        eligible_definition = (
            health.get("exists") is True and lifecycle_state == "active"
        )
        dependency_verified = bool(
            eligible_definition
            and not health.get("missing_dependencies")
            and health.get("readiness_reason") == "dependencies_unverified"
            and dependency_verified
        )
        is_ready = eligible_definition and (
            health.get("healthy") is True or dependency_verified
        )
        is_degraded = (
            eligible_definition
            and not is_ready
            and explicitly_degraded
            and not health.get("missing_dependencies")
        )

        if not is_ready and not is_degraded:
            reason = str(
                health.get("readiness_reason")
                or ("missing_registration" if not health.get("exists") else "unhealthy")
            )
            raise RuntimeError(
                f"Specialist {step.agent_specialist} is not execution-ready: {reason}"
            )

        if is_degraded:
            await self.lifecycle.set_status(
                step.agent_specialist,
                LifecycleStatus.DEGRADED,
            )
            if degraded_agents is not None:
                degraded_agents.append(step.agent_specialist)
            degradation_reason = getattr(
                authorized_plan.degradation_state, "reason_code", None
            ) or str(health.get("readiness_reason") or "policy_authorized_degradation")
            if degradation_reasons is not None:
                degradation_reasons[step.agent_specialist] = degradation_reason
            step.degradation_metadata = DegradationMetadata(
                degraded=True,
                degradation_reason=degradation_reason,
                affected_agent=step.agent_specialist,
                fallback_level=DegradationLevel.PARTIAL,
                capabilities_lost=list(
                    getattr(
                        authorized_plan.degradation_state,
                        "capabilities_lost",
                        [],
                    )
                    or []
                ),
            )

        specialist = self.factory.resolve(registration)

        if emitter is not None:
            await emitter.emit(
                AgentEvent(
                    type=AgentEventType.AGENT_STARTED,
                    agent_id=step.agent_specialist,
                    message=f"step {step.id} started",
                    correlation_id=self._correlation_id(request),
                    metadata={"step_id": step.id, "degraded": is_degraded},
                )
            )

        specialist_plan = replace(
            authorized_plan,
            allowed_tools=list(step.required_tools),
            allowed_plugins=list(step.required_plugins),
            allowed_agents=[step.agent_specialist],
        )
        # Preserve the typed advisory only when it came through the
        # authenticated Runtime and matches the exact Medusa scope. A
        # standalone Medusa caller cannot inject arbitrary learning ranks.
        from ai_karen_engine.core.intelligence.ml.model_outcome_signals import (
            ScopedModelSignals,
        )
        signal = request.context.get("learned_model_signals")
        current_requirements = ExecutionRequirements(**request.execution_requirements)
        canonical_execution_context = request.context.get("execution_context")
        trusted_signal = (
            signal
            if (
                isinstance(signal, ScopedModelSignals)
                and canonical_execution_context is not None
                and getattr(canonical_execution_context, "tenant_id", None) == request.tenant_id
                and getattr(canonical_execution_context, "user_id", None) == request.user_id
                and getattr(canonical_execution_context, "request_id", None) == request.request_id
                and getattr(canonical_execution_context, "correlation_id", None)
                    == current_requirements.correlation_id
                and signal.tenant_id == request.tenant_id
                and signal.user_id == request.user_id
                and signal.task_type == current_requirements.intent
            )
            else None
        )
        prompt_candidate = request.context.get("approved_prompt_messages")
        prompt_status = request.context.get("learning_context_status")
        # PromptRuntime's canonical context is forwarded only when the
        # actual RuntimeExecutionContext belongs to this exact request.
        trusted_prompt = (
            prompt_candidate
            if (
                canonical_execution_context is not None
                and getattr(canonical_execution_context, "tenant_id", None) == request.tenant_id
                and getattr(canonical_execution_context, "user_id", None) == request.user_id
                and getattr(canonical_execution_context, "request_id", None) == request.request_id
                and getattr(canonical_execution_context, "correlation_id", None)
                    == current_requirements.correlation_id
                and isinstance(prompt_candidate, list)
                and bool(prompt_candidate)
                and len(prompt_candidate) <= 100
                and all(
                    isinstance(message, dict)
                    and message.get("role") in {"system", "assistant", "user"}
                    and isinstance(message.get("content"), str)
                    and len(message["content"]) <= 100_000
                    for message in prompt_candidate
                )
            )
            else None
        )
        execution = SpecialistExecutionContext(
            authorized_plan=specialist_plan,
            tenant_id=str(request.tenant_id or "").strip(),
            user_id=str(request.user_id or "").strip(),
            policy_decision_id=authorized_plan.policy_decision_id,
            trajectory_id=request.request_id,
            session_id=request.session_id,
            correlation_id=self._correlation_id(request),
            step_id=step.id,
            preferred_provider=request.context.get("preferred_provider"),
            preferred_model=request.context.get("preferred_model"),
            learning_task_type=current_requirements.intent,
            learned_model_signals=trusted_signal,
            approved_prompt_messages=trusted_prompt,
            learning_context_status=(
                {
                    "status": str(prompt_status.get("status") or "unavailable"),
                    "included_memory_count": int(
                        prompt_status.get("included_memory_count") or 0
                    ),
                }
                if trusted_prompt is not None and isinstance(prompt_status, dict)
                else {"status": "not_supplied", "included_memory_count": 0}
            ),
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
                        correlation_id=self._correlation_id(request),
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
                        correlation_id=self._correlation_id(request),
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

    @staticmethod
    def _require_durable_tool_receipts(results: List[Any]) -> None:
        """Keep post-side-effect audit failures out of partial aggregation."""
        for result in results:
            if isinstance(result, OutcomeStoreError):
                raise result

    def _correlation_id(self, request: RuntimeRequest) -> str:
        requirements = ExecutionRequirements(**request.execution_requirements)
        return requirements.correlation_id

    async def _dependencies_verified_by_completed_steps(
        self,
        *,
        step: PlanStep,
        plan: DeepExecutionPlan,
        unresolved: set[str],
    ) -> bool:
        """Verify dependency readiness from completed provider steps, not catalog hope."""

        if not unresolved:
            return False
        dependency_steps = {
            candidate.id: candidate
            for candidate in plan.steps
            if candidate.id in step.dependencies
        }
        if len(dependency_steps) != len(step.dependencies):
            return False

        provided: set[str] = set()
        for dependency in dependency_steps.values():
            if dependency.status is not StepStatus.COMPLETED:
                return False
            registration = await self.registry.get_agent(dependency.agent_specialist)
            if registration is None:
                return False
            for capability in registration.capabilities:
                name = str(getattr(capability, "name", "") or "").strip()
                cap_type = getattr(getattr(capability, "type", None), "value", None)
                if name:
                    provided.add(name)
                if cap_type:
                    provided.add(str(cap_type).strip())
        return unresolved <= provided
