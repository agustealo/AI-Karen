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
from ai_karen_engine.agent_medusa.execution.run_manager import MedusaRunManager
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
    run_manager.mark_response = AsyncMock()
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
    run_manager.mark_response = AsyncMock()
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
    await manager.mark_response("cancel-race-1", "success")

    snapshot = await manager.get(run_id="cancel-race-1", tenant_id="tenant-1")
    assert snapshot["status"] == "cancelled"
    assert snapshot["outcome_status"] == "cancelled"
    assert snapshot["cancellable"] is False

    with pytest.raises(asyncio.CancelledError):
        await task


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
