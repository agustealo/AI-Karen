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
