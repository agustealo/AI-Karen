from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from ai_karen_engine.agent_medusa.contracts.deep_execution_plan import (
    DeepExecutionPlan,
    PlanStep,
    StepStatus,
)
from ai_karen_engine.agent_medusa.contracts.runtime_request import RuntimeRequest
from ai_karen_engine.agent_medusa.contracts.runtime_response import (
    ResponseStatus,
    RuntimeResponse,
)
from ai_karen_engine.agent_medusa.coordinator.medusa_coordinator import MedusaCoordinator
from ai_karen_engine.agent_medusa.execution.run_manager import (
    ExecutionRunStatus,
    MedusaRunManager,
    RunNotFoundError,
)
from ai_karen_engine.config.agent_medusa import AgentMedusaRuntimeSettings
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    DegradationState,
    ExecutionTopology,
)


def _request() -> RuntimeRequest:
    return RuntimeRequest(
        query="research the request",
        session_id="session-1",
        request_id="req-1",
        user_id="user-1",
        tenant_id="tenant-1",
        context={
            "execution_context": SimpleNamespace(correlation_id="corr-1"),
        },
        authorized_plan={
            "execution_id": "exec-1",
            "policy_decision_id": "policy-1",
            "authorized_user_id": "user-1",
            "authorized_tenant_id": "tenant-1",
            "authorized_session_id": "session-1",
            "topology": "multi_agent",
            "allowed_agents": ["researcher"],
        },
        execution_requirements={
            "request_id": "req-1",
            "correlation_id": "corr-1",
            "requires_agent_delegation": True,
        },
    )


def _plan(*, degradation_state: DegradationState | None = None) -> AuthorizedExecutionPlan:
    return AuthorizedExecutionPlan(
        execution_id="exec-1",
        policy_decision_id="policy-1",
        authorized_user_id="user-1",
        authorized_tenant_id="tenant-1",
        authorized_session_id="session-1",
        topology=ExecutionTopology.MULTI_AGENT,
        allowed_agents=["researcher"],
        degraded_allowed=True,
        degradation_state=degradation_state,
    )


@pytest.mark.asyncio
async def test_partial_response_is_not_recorded_as_successful_run_completion() -> None:
    run_manager = Mock()
    run_manager.register = AsyncMock()
    run_manager.mark_completed = AsyncMock()
    run_manager.mark_failed = AsyncMock()
    run_manager.mark_cancelled = AsyncMock()
    run_manager.mark_response = AsyncMock(return_value=ExecutionRunStatus.COMPLETED)
    coordinator = MedusaCoordinator(run_manager=run_manager)

    with patch.object(
        coordinator,
        "_handle_request",
        new=AsyncMock(
            return_value=RuntimeResponse(
                request_id="req-1",
                status=ResponseStatus.PARTIAL,
                content="partial result",
            )
        ),
    ):
        response = await coordinator.handle_request(_request())

    assert response.status is ResponseStatus.PARTIAL
    run_manager.mark_completed.assert_not_awaited()
    run_manager.mark_failed.assert_not_awaited()
    run_manager.mark_response.assert_awaited_once_with("req-1", "partial")


@pytest.mark.asyncio
async def test_success_response_remains_successful_run_completion() -> None:
    run_manager = Mock()
    run_manager.register = AsyncMock()
    run_manager.mark_completed = AsyncMock()
    run_manager.mark_failed = AsyncMock()
    run_manager.mark_cancelled = AsyncMock()
    run_manager.mark_response = AsyncMock(return_value=ExecutionRunStatus.COMPLETED)
    coordinator = MedusaCoordinator(run_manager=run_manager)

    with patch.object(
        coordinator,
        "_handle_request",
        new=AsyncMock(
            return_value=RuntimeResponse(
                request_id="req-1",
                status=ResponseStatus.SUCCESS,
                content="done",
            )
        ),
    ):
        await coordinator.handle_request(_request())

    run_manager.mark_completed.assert_not_awaited()
    run_manager.mark_failed.assert_not_awaited()
    run_manager.mark_response.assert_awaited_once_with("req-1", "success")


@pytest.mark.asyncio
async def test_unhealthy_specialist_cannot_execute_without_explicit_degradation() -> None:
    registration = SimpleNamespace(capabilities=[], lifecycle_state="active")
    registry = SimpleNamespace(
        get_agent=AsyncMock(return_value=registration),
        get_agent_health=AsyncMock(
            return_value={
                "exists": True,
                "healthy": False,
                "readiness_reason": "dependencies_unavailable",
                "unknown_dependencies": [],
                "missing_dependencies": [],
            }
        ),
    )
    factory = SimpleNamespace(resolve=Mock())
    coordinator = MedusaCoordinator(registry=registry, factory=factory)
    step = PlanStep(id="step-1", agent_specialist="researcher")
    deep_plan = DeepExecutionPlan(request_id="req-1", steps=[step])

    with pytest.raises(RuntimeError, match="not execution-ready"):
        await coordinator._execute_step(
            step,
            deep_plan,
            _request(),
            _plan(),
        )

    factory.resolve.assert_not_called()


@pytest.mark.asyncio
async def test_policy_authorized_degradation_may_execute() -> None:
    specialist = SimpleNamespace(run=AsyncMock(return_value={"ok": True}))
    registration = SimpleNamespace(capabilities=[], lifecycle_state="active")
    registry = SimpleNamespace(
        get_agent=AsyncMock(return_value=registration),
        get_agent_health=AsyncMock(
            return_value={
                "exists": True,
                "healthy": False,
                "readiness_reason": "dependencies_unavailable",
                "unknown_dependencies": [],
            }
        ),
    )
    factory = SimpleNamespace(resolve=Mock(return_value=specialist))
    lifecycle = SimpleNamespace(set_status=AsyncMock())
    coordinator = MedusaCoordinator(
        registry=registry,
        factory=factory,
        lifecycle=lifecycle,
    )
    step = PlanStep(id="step-1", agent_specialist="researcher")
    deep_plan = DeepExecutionPlan(request_id="req-1", steps=[step])
    authorized = _plan(
        degradation_state=DegradationState(
            degraded=True,
            reason_code="optional_dependency_unavailable",
            capabilities_lost=["optional.search"],
        )
    )

    result = await coordinator._execute_step(
        step,
        deep_plan,
        _request(),
        authorized,
    )

    assert result == {"ok": True}
    assert step.status is StepStatus.COMPLETED
    assert specialist.run.await_args.kwargs["execution"].correlation_id == "corr-1"


@pytest.mark.asyncio
async def test_completed_provider_step_verifies_declared_dependency() -> None:
    provider_registration = SimpleNamespace(
        capabilities=[
            SimpleNamespace(
                name="Evidence",
                type=SimpleNamespace(value="research"),
            )
        ]
    )
    registry = SimpleNamespace(
        get_agent=AsyncMock(return_value=provider_registration),
    )
    coordinator = MedusaCoordinator(registry=registry)
    provider_step = PlanStep(
        id="step-0",
        agent_specialist="provider",
        status=StepStatus.COMPLETED,
    )
    dependent_step = PlanStep(
        id="step-1",
        agent_specialist="consumer",
        dependencies=["step-0"],
    )
    deep_plan = DeepExecutionPlan(
        request_id="req-1",
        steps=[provider_step, dependent_step],
    )

    assert await coordinator._dependencies_verified_by_completed_steps(
        step=dependent_step,
        plan=deep_plan,
        unresolved={"Evidence"},
    )


def test_langchain_adapter_has_no_nested_event_loop_or_raw_exception_response() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (
        root
        / "src"
        / "ai_karen_engine"
        / "agent_medusa"
        / "adapters"
        / "frameworks"
        / "langchain_adapter.py"
    ).read_text(encoding="utf-8")

    assert "run_until_complete(" not in source
    assert "content=str(exc)" not in source
    assert 'metadata={"error": str(exc)' not in source
    assert "LangChain specialist execution requires RuntimePolicy plan" in source


def test_step_trace_uses_cortex_correlation_identity() -> None:
    coordinator = MedusaCoordinator()
    assert coordinator._correlation_id(_request()) == "corr-1"


@pytest.mark.asyncio
async def test_cancellation_wins_race_against_late_success_response() -> None:
    settings = AgentMedusaRuntimeSettings(
        distributed_run_control_enabled=False,
        durable_run_ledger_enabled=False,
        durable_run_ledger_required=False,
        worker_id="consumer-reliability-test",
    )
    manager = MedusaRunManager(settings=settings)
    task = asyncio.create_task(asyncio.sleep(30))

    await manager.register(
        run_id="cancel-race-1",
        correlation_id="corr-cancel-race-1",
        request_id="req-cancel-race-1",
        session_id="session-1",
        policy_decision_id="policy-1",
        tenant_id="tenant-1",
        user_id="user-1",
        task=task,
    )
    await manager.cancel(run_id="cancel-race-1", tenant_id="tenant-1")
    resolved = await manager.mark_response("cancel-race-1", "success")
    assert resolved is ExecutionRunStatus.CANCELLED
    assert (
        await manager.mark_response("cancel-race-1", "success")
        is ExecutionRunStatus.CANCELLED
    )

    snapshot = await manager.get(run_id="cancel-race-1", tenant_id="tenant-1")
    assert snapshot["status"] == "cancelled"
    assert snapshot["outcome_status"] == "cancelled"
    assert snapshot["cancellable"] is False

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize("status", list(ResponseStatus))
@pytest.mark.parametrize("cancel", [False, True])
async def test_coordinator_returns_only_authoritative_terminal_outcome(
    status: ResponseStatus, cancel: bool
) -> None:
    manager = MedusaRunManager(
        settings=AgentMedusaRuntimeSettings(
            distributed_run_control_enabled=False,
            durable_run_ledger_enabled=False,
            durable_run_ledger_required=False,
            worker_id="consumer-reliability-test",
        )
    )
    coordinator = MedusaCoordinator(run_manager=manager)
    request = _request()
    entered = asyncio.Event()
    finish = asyncio.Event()
    proposed = RuntimeResponse(
        request_id=request.request_id, status=status, content="assembled result"
    )

    async def execute(_request: RuntimeRequest) -> RuntimeResponse:
        entered.set()
        try:
            await finish.wait()
        except asyncio.CancelledError:
            # Reproduce a specialist swallowing cancellation and returning
            # an assembled result to the real coordinator.
            pass
        return proposed

    with patch.object(coordinator, "_handle_request", new=execute):
        task = asyncio.create_task(coordinator.handle_request(request))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            if cancel:
                await manager.cancel(
                    run_id=request.request_id, tenant_id="tenant-1"
                )
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, timeout=5)
                assert task.cancelled()
                lifecycle = ExecutionRunStatus.CANCELLED
                outcome = "cancelled"
            else:
                finish.set()
                assert await asyncio.wait_for(task, timeout=5) is proposed
                lifecycle = (
                    ExecutionRunStatus.FAILED
                    if status in {ResponseStatus.ERROR, ResponseStatus.TIMEOUT}
                    else ExecutionRunStatus.COMPLETED
                )
                outcome = status.value
            terminal = await manager.get(
                run_id=request.request_id, tenant_id="tenant-1"
            )
            assert terminal["status"] == lifecycle.value
            assert terminal["outcome_status"] == outcome
            assert terminal["cancellable"] is False
        finally:
            if not task.done():
                finish.set()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_response_requires_registered_run() -> None:
    manager = MedusaRunManager(
        settings=AgentMedusaRuntimeSettings(
            distributed_run_control_enabled=False,
            durable_run_ledger_enabled=False,
            durable_run_ledger_required=False,
            worker_id="consumer-reliability-test",
        )
    )
    with pytest.raises(RunNotFoundError):
        await manager.mark_response("unknown", "success")


@pytest.mark.asyncio
async def test_explicit_degradation_cannot_reactivate_disabled_specialist() -> None:
    registration = SimpleNamespace(capabilities=[], lifecycle_state="disabled")
    registry = SimpleNamespace(
        get_agent=AsyncMock(return_value=registration),
        get_agent_health=AsyncMock(
            return_value={
                "exists": True,
                "healthy": False,
                "readiness_reason": "inactive",
                "unknown_dependencies": [],
                "missing_dependencies": [],
            }
        ),
    )
    factory = SimpleNamespace(resolve=Mock())
    coordinator = MedusaCoordinator(registry=registry, factory=factory)
    step = PlanStep(id="step-1", agent_specialist="researcher")
    with pytest.raises(RuntimeError, match="not execution-ready"):
        await coordinator._execute_step(
            step,
            DeepExecutionPlan(request_id="req-1", steps=[step]),
            _request(),
            _plan(
                degradation_state=DegradationState(
                    degraded=True,
                    reason_code="dependency_unavailable",
                )
            ),
        )
    factory.resolve.assert_not_called()


def test_failed_dependency_skips_transitive_dependents_without_blocking_siblings() -> None:
    """A failed branch must not deadlock independent runnable work."""
    failed = PlanStep(id="failed", agent_specialist="a", status=StepStatus.FAILED)
    downstream = PlanStep(id="dependent", agent_specialist="b", dependencies=["failed"])
    transitive = PlanStep(id="transitive", agent_specialist="c", dependencies=["dependent"])
    independent = PlanStep(id="independent", agent_specialist="d")
    plan = DeepExecutionPlan(
        request_id="dag-recovery",
        steps=[transitive, independent, downstream, failed],
    )

    assert plan.mark_blocked_dependents() == 2
    assert downstream.status == StepStatus.SKIPPED
    assert downstream.error == "blocked_dependencies:failed"
    assert transitive.status == StepStatus.SKIPPED
    assert transitive.error == "blocked_dependencies:dependent"
    assert plan.get_next_runnable_steps() == [independent]
    assert plan.mark_blocked_dependents() == 0


def test_completed_dependencies_do_not_block_execution() -> None:
    prerequisite = PlanStep(id="ready", agent_specialist="a", status=StepStatus.COMPLETED)
    downstream = PlanStep(id="dependent", agent_specialist="b", dependencies=["ready"])
    plan = DeepExecutionPlan(request_id="dag-success", steps=[prerequisite, downstream])

    assert plan.mark_blocked_dependents() == 0
    assert downstream.status == StepStatus.PENDING
    assert plan.get_next_runnable_steps() == [downstream]


@pytest.mark.asyncio
@pytest.mark.parametrize("parallelism", [1, 2])
async def test_coordinator_observes_dependency_completion_and_parallelism(
    parallelism: int,
) -> None:
    """Observe the real coordinator loop at a controlled specialist boundary.

    A fixed DAG and test-double invocations isolate scheduling, not providers
    or durable stores. Dependency selection and the budget meter remain real.
    """
    request = _request()
    assert request.authorized_plan is not None
    request.authorized_plan["budget"] = {
        "max_parallelism": parallelism,
        "max_duration_ms": 30000,
        "max_agent_turns": 5,
    }
    steps = [
        PlanStep(
            id="dependent",
            agent_specialist="researcher",
            dependencies=["a", "b", "c"],
        ),
        *[
            PlanStep(id=key, agent_specialist="researcher")
            for key in ("a", "b", "c")
        ],
    ]
    plan = DeepExecutionPlan(request_id=request.request_id, steps=steps)
    planner = SimpleNamespace(create_plan=AsyncMock(return_value=plan))
    assembler = SimpleNamespace(
        assemble=AsyncMock(
            return_value=RuntimeResponse(
                request_id=request.request_id,
                status=ResponseStatus.SUCCESS,
                content="controlled scheduler result",
            )
        )
    )
    coordinator = MedusaCoordinator(planner=planner, assembler=assembler)
    entered = {step.id: asyncio.Event() for step in steps}
    release = {step.id: asyncio.Event() for step in steps}
    active: set[str] = set()
    completed: set[str] = set()
    started: list[str] = []
    peak = 0

    async def execute(
        step, deep_plan, runtime_request, authorized_plan, meter, *_args
    ):
        nonlocal peak
        assert deep_plan is plan
        assert runtime_request is request
        assert authorized_plan.budget.max_parallelism == parallelism
        assert await meter.reserve_agent_turn() is True
        assert set(step.dependencies) <= completed
        assert step.id not in started
        started.append(step.id)
        active.add(step.id)
        peak = max(peak, len(active))
        step.status = StepStatus.RUNNING
        entered[step.id].set()
        try:
            await release[step.id].wait()
            completed.add(step.id)
            step.status = StepStatus.COMPLETED
            return {"step_id": step.id}
        finally:
            active.remove(step.id)

    with patch.object(coordinator, "_execute_step", new=execute):
        task = asyncio.create_task(coordinator._handle_request(request))
        try:
            independent = ["a", "b", "c"]
            for offset in range(0, len(independent), parallelism):
                wave = independent[offset : offset + parallelism]
                await asyncio.wait_for(
                    asyncio.gather(*(entered[key].wait() for key in wave)),
                    timeout=5,
                )
                assert active == set(wave)
                assert set(started) == set(independent[: offset + len(wave)])
                assert not entered["dependent"].is_set()
                for key in wave:
                    release[key].set()

            await asyncio.wait_for(entered["dependent"].wait(), timeout=5)
            assert completed == {"a", "b", "c"}
            assert active == {"dependent"}
            release["dependent"].set()
            response = await asyncio.wait_for(task, timeout=5)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert response.status is ResponseStatus.SUCCESS
    assert peak == parallelism
    assert completed == {"a", "b", "c", "dependent"}
    assert not active
    assert all(step.status is StepStatus.COMPLETED for step in plan.steps)
    assert plan.is_complete
    assert request.request_id not in coordinator.active_plans
    assembler.assemble.assert_awaited_once()
    assert assembler.assemble.await_args.kwargs["status"] is ResponseStatus.SUCCESS


def test_coordinator_parallel_waves_obey_runtime_policy_budget() -> None:
    """Guard against accidentally restoring unbounded gather scheduling."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(MedusaCoordinator))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "gather"
    ]
    assert calls, "Medusa must retain canonical async scheduling"
    bounded_waves = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "runnable_steps"
        and isinstance(node.slice, ast.Slice)
        and isinstance(node.slice.upper, ast.Name)
        and node.slice.upper.id == "max_parallel"
    ]
    assert bounded_waves, "Agent work must respect RuntimePolicy max_parallelism"


def test_coordinator_running_waves_have_hard_deadline_and_timeout_receipt() -> None:
    """The execution deadline must cover awaitable specialists, not only scheduling."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(MedusaCoordinator))
    timeouts = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncWith)
        and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and isinstance(item.context_expr.func.value, ast.Name)
            and item.context_expr.func.value.id == "asyncio"
            and item.context_expr.func.attr == "timeout"
            for item in node.items
        )
    ]
    assert timeouts, "Active specialist waves must be interrupted at the run deadline"
    assert "execution_deadline_exceeded" in inspect.getsource(MedusaCoordinator)


def test_durable_terminal_outcome_is_written_in_same_owner_fenced_transition() -> None:
    """Guard against reintroducing a separate non-atomic outcome update."""
    import inspect

    from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
        PostgresDurableRunLedger,
    )

    transition_source = inspect.getsource(PostgresDurableRunLedger._owned_transition)
    manager_source = inspect.getsource(MedusaRunManager._mark_terminal)
    assert "outcome_status" in transition_source
    assert "jsonb_set" in transition_source
    assert "owner_worker_id = :worker_id" in transition_source
    durable_transition_section = manager_source.split("if run.shared_registered:", 1)[0]
    assert "set_outcome_status" not in durable_transition_section
    assert "outcome_status=outcome_status" in manager_source


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agent", "tool", "plugin"])
async def test_specialist_cannot_widen_parent_authorization_before_side_effects(kind):
    registry = SimpleNamespace(get_agent=AsyncMock(), get_agent_health=AsyncMock())
    factory = SimpleNamespace(resolve=Mock())
    coordinator = MedusaCoordinator(registry=registry, factory=factory)
    step = PlanStep(
        id="step-denied",
        agent_specialist="foreign-agent" if kind == "agent" else "researcher",
        required_tools=["unapproved-tool"] if kind == "tool" else [],
        required_plugins=["unapproved-plugin"] if kind == "plugin" else [],
    )
    plan = _plan()
    with pytest.raises(PermissionError, match="medusa_step_exceeds_authorized_plan"):
        await coordinator._execute_step(
            step,
            DeepExecutionPlan(request_id="req-1", steps=[step]),
            _request(),
            plan,
        )
    registry.get_agent.assert_not_awaited()
    registry.get_agent_health.assert_not_awaited()
    factory.resolve.assert_not_called()
    assert step.status is StepStatus.PENDING


@pytest.mark.asyncio
async def test_approved_specialist_keeps_parent_grants_narrowed():
    """A valid parent grant must execute without widening specialist permissions."""
    specialist = SimpleNamespace(run=AsyncMock(return_value={"ok": True}))
    registration = SimpleNamespace(capabilities=[], lifecycle_state="active")
    registry = SimpleNamespace(
        get_agent=AsyncMock(return_value=registration),
        get_agent_health=AsyncMock(return_value={
            "exists": True,
            "healthy": True,
            "readiness_reason": "ready",
            "unknown_dependencies": [],
            "missing_dependencies": [],
        }),
    )
    coordinator = MedusaCoordinator(
        registry=registry,
        factory=SimpleNamespace(resolve=Mock(return_value=specialist)),
    )
    step = PlanStep(id="step-approved", agent_specialist="researcher")
    result = await coordinator._execute_step(
        step,
        DeepExecutionPlan(request_id="req-1", steps=[step]),
        _request(),
        _plan(),
    )
    assert result == {"ok": True}
    assert step.status is StepStatus.COMPLETED
    execution_plan = specialist.run.await_args.kwargs["execution"].authorized_plan
    assert execution_plan.allowed_agents == ["researcher"]
    assert execution_plan.allowed_tools == []
    assert execution_plan.allowed_plugins == []


@pytest.mark.asyncio
async def test_wildcard_parent_agent_grant_does_not_authorize_specialist():
    registry = SimpleNamespace(get_agent=AsyncMock(), get_agent_health=AsyncMock())
    coordinator = MedusaCoordinator(
        registry=registry,
        factory=SimpleNamespace(resolve=Mock()),
    )
    step = PlanStep(id="step-wildcard", agent_specialist="researcher")
    plan = _plan()
    plan.allowed_agents = ["*"]
    with pytest.raises(PermissionError, match="medusa_step_exceeds_authorized_plan"):
        await coordinator._execute_step(
            step,
            DeepExecutionPlan(request_id="req-1", steps=[step]),
            _request(),
            plan,
        )
    registry.get_agent.assert_not_awaited()
    assert step.status is StepStatus.PENDING
