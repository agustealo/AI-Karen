"""Original ChatRuntime meter may enter Medusa only with authenticated plan scope."""

from __future__ import annotations

from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.agent_medusa.contracts.runtime_request import RuntimeRequest
from ai_karen_engine.agent_medusa.coordinator.medusa_coordinator import (
    MedusaCoordinator,
    _trusted_chat_execution_context,
)
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.outcome.recorder import OutcomeRecorder
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.policy.runtime_policy import (
    PolicyDecision, RuntimePolicyEnforcer,
)
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionBudgetMeter,
    ExecutionTopology,
    DegradationState,
)


def _request(
    *, authenticated: bool = True, shared: bool = True,
    allowed_agents: list[str] | None = None,
):
    budget = ExecutionBudget(max_model_calls=2, max_duration_ms=30000)
    plan = AuthorizedExecutionPlan(
        execution_id="request-a",
        policy_decision_id="policy-a",
        authorized_user_id="user-a",
        authorized_tenant_id="tenant-a",
        authorized_session_id="session-a",
        topology=ExecutionTopology.MULTI_AGENT,
        allowed_agents=(
            list(allowed_agents) if allowed_agents is not None else ["researcher"]
        ),
        budget=budget,
    )
    meter = ExecutionBudgetMeter(budget)
    meter.start()
    context = ChatExecutionContext(
        user_id="user-a",
        tenant_id="tenant-a",
        session_id="session-a",
        request_id="request-a",
        correlation_id="corr-a",
        authenticated_user=(
            UserData(
                user_id="user-a",
                tenant_id="tenant-a",
                roles=["user"],
                permissions=[],
                is_active=True,
                is_verified=True,
            )
            if authenticated else None
        ),
    )
    if authenticated:
        issuer = RuntimePolicyEnforcer()
        issued_decision = PolicyDecision(
            decision_id=plan.policy_decision_id,
            policy_version="fixture",
            allowed=True,
            runtime_constraints={
                "authorized_user_id": context.user_id,
                "authorized_tenant_id": context.tenant_id,
                "authorized_session_id": context.session_id,
                "correlation_id": context.correlation_id,
                "max_model_calls": plan.budget.max_model_calls,
                "allowed_tools": list(plan.allowed_tools),
                "allowed_plugins": list(plan.allowed_plugins),
                "allowed_agents": list(plan.allowed_agents),
            },
        )
        # These tests exercise admission using an original issuer-returned
        # decision object. Policy evaluation itself has separate real-policy
        # integration coverage, never a production test-mode bypass.
        issuer._record_issued_model_decision(issued_decision)
        issuer.bind_chat_model_policy(
            context=context, decision=issued_decision,
        )
        if shared:
            context.bind_runtime_model_authority(plan, meter)
    runtime_request = RuntimeRequest(
        query="Research safely",
        user_id="user-a",
        tenant_id="tenant-a",
        session_id="session-a",
        request_id="request-a",
        context={
            "execution_context": context,
        },
        runtime_budget_meter=meter if shared else None,
        authorized_plan=asdict(plan),
        execution_requirements={
            "request_id": "request-a",
            "correlation_id": "corr-a",
            "intent": "research",
            "requires_agent_delegation": True,
        },
    )
    return runtime_request, plan, meter, context


def test_original_principal_scope_is_required_for_trusted_budget_handoff():
    request, plan, meter, context = _request()
    assert _trusted_chat_execution_context(request, plan) is context
    assert request.runtime_budget_meter is meter
    assert "runtime_budget_meter" not in request.to_dict()


@pytest.mark.parametrize("mutation", [
    "unauthenticated", "revoked", "foreign_tenant",
    "foreign_user", "foreign_session", "foreign_request",
    "foreign_correlation", "foreign_plan",
])
def test_wrong_scope_can_never_be_relabelled_as_original_chat_authority(mutation):
    request, plan, _, context = _request()
    if mutation == "unauthenticated":
        context.authenticated_user = None
    elif mutation == "revoked":
        context.authenticated_user.is_active = False
    elif mutation == "foreign_tenant":
        context.tenant_id = "other-tenant"
    elif mutation == "foreign_user":
        context.user_id = "other-user"
    elif mutation == "foreign_session":
        context.session_id = "other-session"
    elif mutation == "foreign_request":
        context.request_id = "other-request"
    elif mutation == "foreign_correlation":
        context.correlation_id = "other-correlation"
    else:
        plan.authorized_tenant_id = "other-tenant"
    assert _trusted_chat_execution_context(request, plan) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [
    "untrusted_context", "incorrect_budget", "untyped_meter",
])
async def test_medusa_refuses_invalid_shared_meter_before_any_planning(invalid):
    request, plan, _, context = _request()
    if invalid == "untrusted_context":
        context.authenticated_user = None
    elif invalid == "incorrect_budget":
        request.runtime_budget_meter = ExecutionBudgetMeter(
            ExecutionBudget(max_model_calls=999),
        )
    else:
        request.runtime_budget_meter = SimpleNamespace(
            budget=plan.budget, reserve_model_execution=lambda **kwargs: True,
        )

    planner = SimpleNamespace(create_plan=AsyncMock())
    coordinator = object.__new__(MedusaCoordinator)
    coordinator._outcome_recorder = OutcomeRecorder(
        store=SimpleNamespace(save_unique_outcome_async=AsyncMock())
    )
    coordinator.planner = planner
    with pytest.raises(PermissionError, match="medusa_shared_budget_authority_invalid"):
        await coordinator._handle_request(request)
    planner.create_plan.assert_not_awaited()


def test_empty_root_allowlists_cannot_register_new_child_permissions():
    request, root, meter, context = _request(allowed_agents=[])
    assert root.allowed_tools == []
    assert root.allowed_plugins == []
    assert root.allowed_agents == []
    for attribute, value in (
        ("allowed_tools", ["unapproved-tool"]),
        ("allowed_plugins", ["unapproved-plugin"]),
        ("allowed_agents", ["unapproved-agent"]),
    ):
        forged = replace(root, **{attribute: value})
        with pytest.raises(
            PermissionError, match="runtime_model_execution_authority_invalid",
        ):
            context.register_runtime_model_child_plan(forged, meter)
        assert not context.is_runtime_model_plan_authorized(forged, meter)
    assert meter.model_calls == 0
    assert request.runtime_budget_meter is meter


@pytest.mark.asyncio
async def test_empty_root_allowlists_reject_serialized_handoff_widening():
    request, root, meter, context = _request(allowed_agents=[])
    request.authorized_plan = asdict(
        replace(root, allowed_tools=["unapproved-tool"]),
    )
    coordinator = object.__new__(MedusaCoordinator)
    coordinator._outcome_recorder = OutcomeRecorder(
        store=SimpleNamespace(save_unique_outcome_async=AsyncMock())
    )
    coordinator.planner = SimpleNamespace(create_plan=AsyncMock())
    with pytest.raises(
        PermissionError, match="medusa_shared_budget_authority_invalid",
    ):
        await coordinator._handle_request(request)
    coordinator.planner.create_plan.assert_not_awaited()
    assert context.original_runtime_model_plan(meter) is root
    assert meter.model_calls == 0


@pytest.mark.asyncio
async def test_mutated_original_empty_root_permissions_cannot_authorize_handoff():
    # The root object remains the same, but its grants cannot gain tools,
    # plugins or agents after policy admission.
    for attribute, value in (
        ("allowed_tools", "unapproved-tool"),
        ("allowed_plugins", "unapproved-plugin"),
        ("allowed_agents", "unapproved-agent"),
    ):
        request, root, meter, context = _request(allowed_agents=[])
        getattr(root, attribute).append(value)
        request.authorized_plan = asdict(root)
        planner = SimpleNamespace(create_plan=AsyncMock())
        coordinator = object.__new__(MedusaCoordinator)
    coordinator._outcome_recorder = OutcomeRecorder(
        store=SimpleNamespace(save_unique_outcome_async=AsyncMock())
    )
        coordinator.planner = planner
        with pytest.raises(
            PermissionError, match="medusa_shared_budget_authority_invalid",
        ):
            await coordinator._handle_request(request)
        planner.create_plan.assert_not_awaited()
        assert context.original_runtime_model_plan(meter) is None
        assert meter.model_calls == 0


def test_mutated_authorized_child_cannot_execute_new_permissions():
    _request_value, root, meter, context = _request(
        allowed_agents=["researcher"],
    )
    child = replace(root, allowed_agents=[])
    context.register_runtime_model_child_plan(child, meter)
    assert context.is_runtime_model_plan_authorized(child, meter)
    child.allowed_agents.append("unapproved-agent")
    assert not context.is_runtime_model_plan_authorized(child, meter)
    assert context.original_runtime_model_plan(meter) is root


@pytest.mark.asyncio
async def test_shared_medusa_restricts_serialized_handoff_to_one_specialist():
    request, root, meter, context = _request(
        allowed_agents=["analyst", "researcher"],
    )
    request.authorized_plan = asdict(replace(root, allowed_agents=["analyst"]))
    coordinator = object.__new__(MedusaCoordinator)
    coordinator._outcome_recorder = OutcomeRecorder(
        store=SimpleNamespace(save_unique_outcome_async=AsyncMock())
    )
    coordinator.registry = SimpleNamespace()
    coordinator.planner = SimpleNamespace(
        create_plan=AsyncMock(side_effect=RuntimeError("planner_sentinel")),
    )
    with pytest.raises(RuntimeError, match="planner_sentinel"):
        await coordinator._handle_request(request)
    narrowed = coordinator.planner.create_plan.await_args.kwargs["authorized_plan"]
    assert narrowed is not root
    assert narrowed.allowed_agents == ["analyst"]
    assert narrowed.budget is root.budget
    assert narrowed.budget is meter.budget
    assert context.is_runtime_model_plan_authorized(narrowed, meter)
    assert context.original_runtime_model_plan(meter) is root


@pytest.mark.asyncio
async def test_shared_medusa_rejects_widened_specialist_handoff():
    request, _root, meter, context = _request(allowed_agents=["analyst"])
    request.authorized_plan["allowed_agents"] = ["analyst", "unapproved"]
    coordinator = object.__new__(MedusaCoordinator)
    coordinator._outcome_recorder = OutcomeRecorder(
        store=SimpleNamespace(save_unique_outcome_async=AsyncMock())
    )
    coordinator.planner = SimpleNamespace(create_plan=AsyncMock())
    with pytest.raises(
        PermissionError, match="medusa_shared_budget_authority_invalid",
    ):
        await coordinator._handle_request(request)
    coordinator.planner.create_plan.assert_not_awaited()
    assert context.original_runtime_model_plan(meter) is not None
    assert meter.model_calls == 0


@pytest.mark.asyncio
async def test_standalone_authenticated_medusa_binds_own_real_meter_once():
    request, _, _, context = _request(shared=False)
    planner = SimpleNamespace(
        create_plan=AsyncMock(side_effect=RuntimeError("planner_sentinel")),
    )
    coordinator = object.__new__(MedusaCoordinator)
    coordinator._outcome_recorder = OutcomeRecorder(
        store=SimpleNamespace(save_unique_outcome_async=AsyncMock())
    )
    coordinator.planner = planner
    coordinator.registry = SimpleNamespace()
    with pytest.raises(RuntimeError, match="planner_sentinel"):
        await coordinator._handle_request(request)
    planner.create_plan.assert_awaited_once()
    reconstructed_plan = planner.create_plan.await_args.kwargs["authorized_plan"]
    bound_plan, bound_meter = context.__dict__["_runtime_model_authority"]
    assert reconstructed_plan is bound_plan
    assert bound_meter.budget is reconstructed_plan.budget
    assert context.original_runtime_model_plan(bound_meter) is bound_plan
    assert bound_meter.model_calls == 0


@pytest.mark.asyncio
async def test_shared_medusa_degradation_metadata_restores_original_plan_identity():
    request, plan, meter, _ = _request()
    plan.degradation_state = DegradationState(
        degraded=True, reason_code="diagnostic-only", level="medium",
    )
    request.authorized_plan = asdict(plan)
    planner = SimpleNamespace(
        create_plan=AsyncMock(side_effect=RuntimeError("planner_sentinel")),
    )
    coordinator = object.__new__(MedusaCoordinator)
    coordinator._outcome_recorder = OutcomeRecorder(
        store=SimpleNamespace(save_unique_outcome_async=AsyncMock())
    )
    coordinator.planner = planner
    coordinator.registry = SimpleNamespace()
    with pytest.raises(RuntimeError, match="planner_sentinel"):
        await coordinator._handle_request(request)
    planner.create_plan.assert_awaited_once()
    assert planner.create_plan.await_args.kwargs["authorized_plan"] is plan
    assert planner.create_plan.await_args.kwargs["budget"] is meter.budget


@pytest.mark.asyncio
async def test_valid_original_shared_budget_reaches_existing_planner_without_reset():
    request, _, meter, _ = _request()
    assert await meter.reserve_model_execution() is True
    planner = SimpleNamespace(
        create_plan=AsyncMock(side_effect=RuntimeError("planner_sentinel")),
    )
    coordinator = object.__new__(MedusaCoordinator)
    coordinator._outcome_recorder = OutcomeRecorder(
        store=SimpleNamespace(save_unique_outcome_async=AsyncMock())
    )
    coordinator.planner = planner
    # The valid path reaches the real coordinator's planner call, which
    # explicitly receives the canonical registry. Provide that dependency.
    coordinator.registry = SimpleNamespace()
    with pytest.raises(RuntimeError, match="planner_sentinel"):
        await coordinator._handle_request(request)
    planner.create_plan.assert_awaited_once()
    # The planner/specialists must see the original Runtime budget object,
    # not an equal deserialized copy that fails shared-meter identity checks.
    handed_plan = planner.create_plan.await_args.kwargs["authorized_plan"]
    assert handed_plan.budget is meter.budget
    assert planner.create_plan.await_args.kwargs["budget"] is meter.budget
    assert request.runtime_budget_meter is meter
    assert meter.model_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["authorization", "child_admission", "busy"])
async def test_specialist_pre_invocation_failure_emits_no_start(failure):
    from ai_karen_engine.agent_medusa.contracts.deep_execution_plan import (
        DeepExecutionPlan,
        PlanStep,
    )
    from ai_karen_engine.agent_medusa.execution.event_emitter import EventEmitter

    request, root, meter, context = _request()
    step = PlanStep(agent_specialist="researcher")
    plan = DeepExecutionPlan(request_id=request.request_id, steps=[step])
    specialist = SimpleNamespace(run=AsyncMock())
    registration = SimpleNamespace(lifecycle_state="active")
    coordinator = object.__new__(MedusaCoordinator)
    coordinator._outcome_recorder = OutcomeRecorder(
        store=SimpleNamespace(save_unique_outcome_async=AsyncMock())
    )
    coordinator.registry = SimpleNamespace(
        get_agent=AsyncMock(return_value=registration),
        get_agent_health=AsyncMock(return_value={"exists": True, "healthy": True}),
    )
    coordinator.factory = SimpleNamespace(resolve=lambda _: specialist)
    coordinator.lifecycle = SimpleNamespace(set_status=AsyncMock())
    emitter = EventEmitter()

    if failure == "authorization":
        step.required_tools = ["unapproved-tool"]
    elif failure == "child_admission":
        context.authenticated_user = None
    else:
        coordinator.lifecycle.set_status.side_effect = RuntimeError("busy_sentinel")

    with pytest.raises((PermissionError, RuntimeError)):
        await coordinator._execute_step(
            step, plan, request, root, meter, emitter,
        )
    specialist.run.assert_not_awaited()
    assert emitter.events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_admitted_specialist_emits_correlated_start_and_terminal_event(fails):
    from ai_karen_engine.agent_medusa.contracts.deep_execution_plan import (
        DeepExecutionPlan,
        PlanStep,
    )
    from ai_karen_engine.agent_medusa.contracts.events import AgentEventType
    from ai_karen_engine.agent_medusa.execution.event_emitter import EventEmitter

    request, root, meter, _ = _request()
    step = PlanStep(agent_specialist="researcher")
    plan = DeepExecutionPlan(request_id=request.request_id, steps=[step])
    emitter = EventEmitter()

    async def invoke(*args, **kwargs):
        assert [event.type for event in emitter.events] == [AgentEventType.AGENT_STARTED]
        if fails:
            raise RuntimeError("specialist_sentinel")
        return {"result": "observed"}

    specialist = SimpleNamespace(run=AsyncMock(side_effect=invoke))
    coordinator = object.__new__(MedusaCoordinator)
    coordinator._outcome_recorder = OutcomeRecorder(
        store=SimpleNamespace(save_unique_outcome_async=AsyncMock())
    )
    coordinator.registry = SimpleNamespace(
        get_agent=AsyncMock(return_value=SimpleNamespace(lifecycle_state="active")),
        get_agent_health=AsyncMock(return_value={"exists": True, "healthy": True}),
    )
    coordinator.factory = SimpleNamespace(resolve=lambda _: specialist)
    coordinator.lifecycle = SimpleNamespace(set_status=AsyncMock())
    if fails:
        with pytest.raises(RuntimeError, match="specialist_sentinel"):
            await coordinator._execute_step(step, plan, request, root, meter, emitter)
    else:
        assert await coordinator._execute_step(
            step, plan, request, root, meter, emitter
        ) == {"result": "observed"}
    specialist.run.assert_awaited_once()
    assert [event.type for event in emitter.events] == [
        AgentEventType.AGENT_STARTED,
        AgentEventType.AGENT_FAILED if fails else AgentEventType.AGENT_COMPLETED,
    ]
    for event in emitter.events:
        assert event.agent_id == "researcher"
        assert event.correlation_id == "corr-a"
        assert event.metadata["step_id"] == step.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    ["unauthenticated", "revoked", "foreign_user", "foreign_tenant",
     "foreign_request", "foreign_correlation", "unregistered_plan",
     "substituted_meter", "wrong_specialist", "widened_child"],
)
async def test_participation_writer_rejects_invalid_authority_before_io(mutation):
    from ai_karen_engine.core.runtime.outcome.contracts import (
        SpecialistParticipationPhase,
    )
    from ai_karen_engine.core.runtime.outcome.recorder import OutcomeRecorder

    _, root, meter, context = _request(allowed_agents=["researcher", "analyst"])
    child = replace(root, allowed_agents=["researcher"])
    context.register_runtime_model_child_plan(child, meter)
    specialist_id = "researcher"
    if mutation == "unauthenticated":
        context.authenticated_user = None
    elif mutation == "revoked":
        context.authenticated_user.is_active = False
    elif mutation == "foreign_user":
        context.user_id = "other-user"
    elif mutation == "foreign_tenant":
        context.tenant_id = "other-tenant"
    elif mutation == "foreign_request":
        context.request_id = "other-request"
    elif mutation == "foreign_correlation":
        context.correlation_id = "other-correlation"
    elif mutation == "unregistered_plan":
        child = replace(child)
    elif mutation == "substituted_meter":
        meter = ExecutionBudgetMeter(root.budget)
        meter.start()
    elif mutation == "wrong_specialist":
        specialist_id = "analyst"
    elif mutation == "widened_child":
        child.allowed_agents.append("analyst")
    store = SimpleNamespace(save_unique_outcome_async=AsyncMock())
    with pytest.raises(PermissionError):
        await OutcomeRecorder(store=store).record_specialist_participation_async(
            context=context, plan=child, meter=meter,
            step_id="step-a", specialist_id=specialist_id,
            phase=SpecialistParticipationPhase.STARTED,
        )
    store.save_unique_outcome_async.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["stored", "failed", "missing"])
async def test_participation_writer_acknowledges_only_completed_strict_append(mode):
    from ai_karen_engine.core.runtime.outcome.contracts import (
        SpecialistParticipationPhase,
    )
    from ai_karen_engine.core.runtime.outcome.recorder import OutcomeRecorder
    from ai_karen_engine.core.runtime.outcome.store import OutcomeStoreError

    _, root, meter, context = _request()
    child = replace(root, allowed_agents=["researcher"])
    context.register_runtime_model_child_plan(child, meter)
    observed = []

    async def append(payload):
        observed.append(payload)
        if mode == "failed":
            raise OutcomeStoreError("append failed")

    store = SimpleNamespace(save_unique_outcome_async=AsyncMock(side_effect=append))
    recorder = OutcomeRecorder(store=None if mode == "missing" else store)
    kwargs = dict(
        context=context, plan=child, meter=meter,
        step_id="step-a", specialist_id="researcher",
        phase=SpecialistParticipationPhase.COMPLETED,
    )
    if mode == "stored":
        receipt = await recorder.record_specialist_participation_async(**kwargs)
        assert observed == [receipt.to_evidence_payload()]
        assert receipt.tenant_id == context.tenant_id
        assert receipt.user_id == context.user_id
        assert receipt.trajectory_id == context.request_id
        assert receipt.correlation_id == context.correlation_id
    else:
        with pytest.raises(OutcomeStoreError):
            await recorder.record_specialist_participation_async(**kwargs)
    if mode == "missing":
        store.save_unique_outcome_async.assert_not_awaited()
    else:
        store.save_unique_outcome_async.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["before_call", "inside_call", "after_return"])
async def test_specialist_cancellation_preserves_observed_execution_boundary(boundary):
    import asyncio

    from ai_karen_engine.agent_medusa.contracts.deep_execution_plan import (
        DeepExecutionPlan,
        PlanStep,
        StepStatus,
    )
    from ai_karen_engine.agent_medusa.contracts.events import AgentEventType
    from ai_karen_engine.agent_medusa.execution.event_emitter import EventEmitter
    from ai_karen_engine.agent_medusa.lifecycle.lifecycle_manager import LifecycleStatus

    request, root, meter, _ = _request()
    step = PlanStep(agent_specialist="researcher")
    plan = DeepExecutionPlan(request_id=request.request_id, steps=[step])

    class InterruptingEmitter(EventEmitter):
        async def emit(self, event):
            if (
                boundary == "before_call"
                and event.type == AgentEventType.AGENT_STARTED
            ):
                raise asyncio.CancelledError
            if (
                boundary == "after_return"
                and event.type == AgentEventType.AGENT_COMPLETED
            ):
                raise asyncio.CancelledError
            await super().emit(event)

    async def invoke(*args, **kwargs):
        if boundary == "inside_call":
            raise asyncio.CancelledError
        return {"result": "observed"}

    emitter = InterruptingEmitter()
    specialist = SimpleNamespace(run=AsyncMock(side_effect=invoke))
    coordinator = object.__new__(MedusaCoordinator)
    coordinator._outcome_recorder = OutcomeRecorder(
        store=SimpleNamespace(save_unique_outcome_async=AsyncMock())
    )
    coordinator.registry = SimpleNamespace(
        get_agent=AsyncMock(return_value=SimpleNamespace(lifecycle_state="active")),
        get_agent_health=AsyncMock(return_value={"exists": True, "healthy": True}),
    )
    coordinator.factory = SimpleNamespace(resolve=lambda _: specialist)
    coordinator.lifecycle = SimpleNamespace(set_status=AsyncMock())

    with pytest.raises(asyncio.CancelledError):
        await coordinator._execute_step(step, plan, request, root, meter, emitter)

    assert coordinator.lifecycle.set_status.await_args.args == (
        "researcher",
        LifecycleStatus.IDLE,
    )
    if boundary == "before_call":
        specialist.run.assert_not_awaited()
    else:
        specialist.run.assert_awaited_once()
    interruptions = [
        event
        for event in emitter.events
        if event.type == AgentEventType.AGENT_INTERRUPTED
    ]
    if boundary == "after_return":
        assert step.status == StepStatus.COMPLETED
        assert step.output_data == {"result": "observed"}
        assert step.error is None
        assert not interruptions
    else:
        assert step.status == StepStatus.FAILED
        assert step.error == "cancelled"
        assert step.output_data is None
        assert len(interruptions) == 1
        event = interruptions[0]
        assert event.agent_id == "researcher"
        assert event.correlation_id == "corr-a"
        assert event.metadata["step_id"] == step.id
        assert event.metadata["reason_code"] == "cancelled"
        assert event.metadata["invocation_entered"] is (boundary == "inside_call")


@pytest.mark.asyncio
@pytest.mark.parametrize("exhausted", [True, False])
async def test_scheduler_emits_each_skipped_step_once(exhausted):
    from ai_karen_engine.agent_medusa.contracts.deep_execution_plan import (
        DeepExecutionPlan,
        PlanStep,
        StepStatus,
    )
    from ai_karen_engine.agent_medusa.contracts.events import AgentEventType

    request, _, meter, _ = _request()
    first = PlanStep(id="first", agent_specialist="researcher")
    second = PlanStep(
        id="second", agent_specialist="researcher", dependencies=["first"]
    )
    third = PlanStep(
        id="third", agent_specialist="researcher", dependencies=["second"]
    )
    plan = DeepExecutionPlan(request_id=request.request_id, steps=[first, second, third])
    events = []
    coordinator = object.__new__(MedusaCoordinator)
    coordinator._outcome_recorder = OutcomeRecorder(
        store=SimpleNamespace(save_unique_outcome_async=AsyncMock())
    )
    coordinator.registry = SimpleNamespace()
    coordinator.planner = SimpleNamespace(create_plan=AsyncMock(return_value=plan))
    coordinator.active_plans = {}
    coordinator.trajectories = {}
    coordinator._global_sinks = [events.append]
    coordinator.assembler = SimpleNamespace(assemble=AsyncMock())

    if exhausted:
        assert await meter.reserve_model_execution()
        assert await meter.reserve_model_execution()
        # Reaching the quota is not a denied reservation. The shared meter
        # becomes exhausted only after a further request is rejected.
        assert not await meter.reserve_model_execution()
        assert meter.exhausted
        assert meter.model_calls == 2

    coordinator._execute_step = AsyncMock(side_effect=RuntimeError("step_failure"))
    await coordinator._handle_request(request)

    skipped = [event for event in events if event.type == AgentEventType.AGENT_SKIPPED]
    expected_ids = ["first", "second", "third"] if exhausted else ["second", "third"]
    assert [event.metadata["step_id"] for event in skipped] == expected_ids
    for event in skipped:
        assert event.correlation_id == "corr-a"
        assert event.agent_id == "researcher"
        assert event.metadata["reason_code"] == (
            "execution_budget_exhausted" if exhausted else "dependency_blocked"
        )
    assert all(step.status == StepStatus.SKIPPED for step in plan.steps[1:])
    if exhausted:
        coordinator._execute_step.assert_not_awaited()
        assert first.status == StepStatus.SKIPPED
    else:
        coordinator._execute_step.assert_awaited_once()
        assert first.status == StepStatus.FAILED


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["completion_event", "idle_cleanup"])
async def test_post_invocation_failure_does_not_emit_false_specialist_failure(boundary):
    from ai_karen_engine.agent_medusa.contracts.deep_execution_plan import (
        DeepExecutionPlan,
        PlanStep,
        StepStatus,
    )
    from ai_karen_engine.agent_medusa.contracts.events import AgentEventType
    from ai_karen_engine.agent_medusa.execution.event_emitter import EventEmitter
    from ai_karen_engine.agent_medusa.lifecycle.lifecycle_manager import LifecycleStatus

    request, root, meter, _ = _request()
    step = PlanStep(agent_specialist="researcher")
    plan = DeepExecutionPlan(request_id=request.request_id, steps=[step])

    class FailingEmitter(EventEmitter):
        async def emit(self, event):
            if boundary == "completion_event" and event.type == AgentEventType.AGENT_COMPLETED:
                raise RuntimeError("post_invocation_failure")
            await super().emit(event)

    async def set_status(agent, status):
        if boundary == "idle_cleanup" and status == LifecycleStatus.IDLE:
            raise RuntimeError("post_invocation_failure")

    emitter = FailingEmitter()
    specialist = SimpleNamespace(run=AsyncMock(return_value={"result": "observed"}))
    coordinator = object.__new__(MedusaCoordinator)
    coordinator._outcome_recorder = OutcomeRecorder(
        store=SimpleNamespace(save_unique_outcome_async=AsyncMock())
    )
    coordinator.registry = SimpleNamespace(
        get_agent=AsyncMock(return_value=SimpleNamespace(lifecycle_state="active")),
        get_agent_health=AsyncMock(return_value={"exists": True, "healthy": True}),
    )
    coordinator.factory = SimpleNamespace(resolve=lambda _: specialist)
    coordinator.lifecycle = SimpleNamespace(set_status=AsyncMock(side_effect=set_status))

    with pytest.raises(RuntimeError, match="post_invocation_failure"):
        await coordinator._execute_step(step, plan, request, root, meter, emitter)

    specialist.run.assert_awaited_once()
    assert step.status == StepStatus.COMPLETED
    assert step.output_data == {"result": "observed"}
    assert step.error is None
    assert all(event.type != AgentEventType.AGENT_FAILED for event in emitter.events)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_wave_propagates_post_invocation_error_without_rewriting_completed_step(cancelled):
    import asyncio

    from ai_karen_engine.agent_medusa.contracts.deep_execution_plan import (
        DeepExecutionPlan,
        PlanStep,
        StepStatus,
    )

    request, _, _, _ = _request()
    step = PlanStep(agent_specialist="researcher")
    plan = DeepExecutionPlan(request_id=request.request_id, steps=[step])
    coordinator = object.__new__(MedusaCoordinator)
    coordinator._outcome_recorder = OutcomeRecorder(
        store=SimpleNamespace(save_unique_outcome_async=AsyncMock())
    )
    coordinator.registry = SimpleNamespace()
    coordinator.planner = SimpleNamespace(create_plan=AsyncMock(return_value=plan))
    coordinator.active_plans = {}
    coordinator.trajectories = {}
    coordinator._global_sinks = []
    coordinator.assembler = SimpleNamespace(assemble=AsyncMock())
    error = asyncio.CancelledError if cancelled else RuntimeError

    async def execute(*args, **kwargs):
        step.status = StepStatus.COMPLETED
        step.output_data = {"result": "observed"}
        raise error("post_invocation_failure")

    coordinator._execute_step = AsyncMock(side_effect=execute)
    with pytest.raises(error):
        await coordinator._handle_request(request)

    assert step.status == StepStatus.COMPLETED
    assert step.output_data == {"result": "observed"}
    assert step.error is None
    coordinator._execute_step.assert_awaited_once()
    coordinator.assembler.assemble.assert_not_awaited()
    assert request.request_id not in coordinator.active_plans


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["completed", "failed", "interrupted", "before_call", "append_failed"])
async def test_coordinator_records_only_observed_terminal_participation(boundary):
    import asyncio

    from ai_karen_engine.agent_medusa.contracts.deep_execution_plan import (
        DeepExecutionPlan,
        PlanStep,
        StepStatus,
    )
    from ai_karen_engine.agent_medusa.contracts.events import AgentEventType
    from ai_karen_engine.agent_medusa.execution.event_emitter import EventEmitter
    from ai_karen_engine.core.runtime.outcome.store import OutcomeStoreError

    request, root, meter, _ = _request()
    step = PlanStep(agent_specialist="researcher")
    plan = DeepExecutionPlan(request_id=request.request_id, steps=[step])
    pending = set()
    store = SimpleNamespace(save_unique_outcome_async=AsyncMock())

    class InterruptingEmitter(EventEmitter):
        async def emit(self, event):
            if boundary == "before_call" and event.type == AgentEventType.AGENT_STARTED:
                raise asyncio.CancelledError
            await super().emit(event)

    async def invoke(*args, **kwargs):
        store.save_unique_outcome_async.assert_not_awaited()
        if boundary == "failed":
            raise RuntimeError("invocation_failed")
        if boundary == "interrupted":
            raise asyncio.CancelledError
        return {"result": "observed"}

    async def append(payload):
        if boundary == "append_failed":
            raise OutcomeStoreError("append failed")

    store.save_unique_outcome_async.side_effect = append
    specialist = SimpleNamespace(run=AsyncMock(side_effect=invoke))
    emitter = InterruptingEmitter()
    coordinator = MedusaCoordinator(
        registry=SimpleNamespace(
            get_agent=AsyncMock(return_value=SimpleNamespace(lifecycle_state="active")),
            get_agent_health=AsyncMock(return_value={"exists": True, "healthy": True}),
        ),
        factory=SimpleNamespace(resolve=lambda _: specialist),
        lifecycle=SimpleNamespace(set_status=AsyncMock()),
        outcome_recorder=OutcomeRecorder(store=store),
    )

    async def execute():
        return await coordinator._execute_step(
            step, plan, request, root, meter, emitter,
            pending_participation=pending,
        )

    if boundary in {"before_call", "interrupted"}:
        with pytest.raises(asyncio.CancelledError):
            await execute()
    elif boundary == "failed":
        with pytest.raises(RuntimeError, match="invocation_failed"):
            await execute()
    elif boundary == "append_failed":
        with pytest.raises(OutcomeStoreError, match="append failed"):
            await execute()
    else:
        assert await execute() == {"result": "observed"}

    if boundary == "before_call":
        specialist.run.assert_not_awaited()
        store.save_unique_outcome_async.assert_not_awaited()
        assert not pending
        return

    specialist.run.assert_awaited_once()
    store.save_unique_outcome_async.assert_awaited_once()
    payload = store.save_unique_outcome_async.await_args.args[0]
    assert payload["tenant_id"] == "tenant-a"
    assert payload["user_id"] == "user-a"
    assert payload["trajectory_id"] == "request-a"
    assert payload["correlation_id"] == "corr-a"
    assert payload["metadata"]["step_id"] == step.id
    assert payload["metadata"]["specialist_id"] == "researcher"
    assert payload["metadata"]["phase"] == (
        "completed" if boundary == "append_failed" else boundary
    )
    if boundary in {"completed", "append_failed"}:
        assert step.status == StepStatus.COMPLETED
        assert step.output_data == {"result": "observed"}
        assert not any(event.type == AgentEventType.AGENT_FAILED for event in emitter.events)
    assert pending == ({step.id} if boundary == "append_failed" else set())


@pytest.mark.asyncio
async def test_wave_timeout_during_completion_receipt_cannot_assemble_success():
    import asyncio

    from ai_karen_engine.agent_medusa.contracts.deep_execution_plan import (
        DeepExecutionPlan,
        PlanStep,
        StepStatus,
    )
    from ai_karen_engine.core.runtime.outcome.store import OutcomeStoreError

    request, _, meter, _ = _request()
    step = PlanStep(agent_specialist="researcher")
    plan = DeepExecutionPlan(request_id=request.request_id, steps=[step])

    async def append(payload):
        await asyncio.Event().wait()

    store = SimpleNamespace(save_unique_outcome_async=AsyncMock(side_effect=append))
    specialist = SimpleNamespace(run=AsyncMock(return_value={"result": "observed"}))
    coordinator = MedusaCoordinator(
        planner=SimpleNamespace(create_plan=AsyncMock(return_value=plan)),
        registry=SimpleNamespace(
            get_agent=AsyncMock(return_value=SimpleNamespace(lifecycle_state="active")),
            get_agent_health=AsyncMock(return_value={"exists": True, "healthy": True}),
        ),
        factory=SimpleNamespace(resolve=lambda _: specialist),
        lifecycle=SimpleNamespace(set_status=AsyncMock()),
        assembler=SimpleNamespace(assemble=AsyncMock()),
        outcome_recorder=OutcomeRecorder(store=store),
    )
    # Bound the wave rather than wall-clock sleeps or a real database.
    meter.remaining_duration_ms = AsyncMock(return_value=50)
    with pytest.raises(OutcomeStoreError, match="acknowledgement unavailable"):
        await coordinator._handle_request(request)

    specialist.run.assert_awaited_once()
    store.save_unique_outcome_async.assert_awaited_once()
    assert step.status == StepStatus.COMPLETED
    assert step.output_data == {"result": "observed"}
    coordinator.assembler.assemble.assert_not_awaited()
    assert request.request_id not in coordinator.active_plans
