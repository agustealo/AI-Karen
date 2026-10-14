from __future__ import annotations

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
from ai_karen_engine.agent_medusa.coordinator.medusa_coordinator import (
    MedusaCoordinator,
    MedusaPartialOutcome,
)
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
    run_manager.mark_failed.assert_awaited_once()
    failure = run_manager.mark_failed.await_args.args[1]
    assert isinstance(failure, MedusaPartialOutcome)


@pytest.mark.asyncio
async def test_success_response_remains_successful_run_completion() -> None:
    run_manager = Mock()
    run_manager.register = AsyncMock()
    run_manager.mark_completed = AsyncMock()
    run_manager.mark_failed = AsyncMock()
    run_manager.mark_cancelled = AsyncMock()
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

    run_manager.mark_completed.assert_awaited_once_with("req-1")
    run_manager.mark_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_unhealthy_specialist_cannot_execute_without_explicit_degradation() -> None:
    registration = SimpleNamespace(capabilities=[])
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
    registration = SimpleNamespace(capabilities=[])
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
