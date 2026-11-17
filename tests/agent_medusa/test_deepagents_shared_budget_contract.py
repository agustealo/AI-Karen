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
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionBudgetMeter,
    ExecutionTopology,
)


def _request(*, authenticated: bool = True):
    budget = ExecutionBudget(max_model_calls=2, max_duration_ms=30000)
    plan = AuthorizedExecutionPlan(
        execution_id="request-a",
        policy_decision_id="policy-a",
        authorized_user_id="user-a",
        authorized_tenant_id="tenant-a",
        authorized_session_id="session-a",
        topology=ExecutionTopology.MULTI_AGENT,
        allowed_agents=["researcher"],
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
    runtime_request = RuntimeRequest(
        query="Research safely",
        user_id="user-a",
        tenant_id="tenant-a",
        session_id="session-a",
        request_id="request-a",
        context={
            "execution_context": context,
        },
        runtime_budget_meter=meter,
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
    coordinator.planner = planner
    with pytest.raises(PermissionError, match="medusa_shared_budget_authority_invalid"):
        await coordinator._handle_request(request)
    planner.create_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_original_shared_budget_reaches_existing_planner_without_reset():
    request, _, meter, _ = _request()
    assert await meter.reserve_model_execution() is True
    planner = SimpleNamespace(
        create_plan=AsyncMock(side_effect=RuntimeError("planner_sentinel")),
    )
    coordinator = object.__new__(MedusaCoordinator)
    coordinator.planner = planner
    # The valid path reaches the real coordinator's planner call, which
    # explicitly receives the canonical registry. Provide that dependency.
    coordinator.registry = SimpleNamespace()
    with pytest.raises(RuntimeError, match="planner_sentinel"):
        await coordinator._handle_request(request)
    planner.create_plan.assert_awaited_once()
    assert request.runtime_budget_meter is meter
    assert meter.model_calls == 1
