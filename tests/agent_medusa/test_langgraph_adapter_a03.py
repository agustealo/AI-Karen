"""LangGraph whole-plan adapter must only delegate to canonical Medusa."""
from unittest.mock import AsyncMock, patch

import pytest

from ai_karen_engine.agent_medusa.adapters.frameworks.langgraph_adapter import (
    MedusaLangGraphAdapter,
)
from ai_karen_engine.agent_medusa.contracts.runtime_request import RuntimeRequest
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionTopology,
)


def _plan(**overrides):
    fields = {
        "execution_id": "execution-1",
        "policy_decision_id": "policy-1",
        "authorized_user_id": "user-1",
        "authorized_tenant_id": "tenant-1",
        "authorized_session_id": "session-1",
        "topology": ExecutionTopology.MULTI_AGENT,
        "allowed_agents": ["analyst"],
    }
    fields.update(overrides)
    return AuthorizedExecutionPlan(**fields)


def _request(*, requirements=True, policy=True):
    return RuntimeRequest(
        query="analyze",
        request_id="request-1",
        session_id="session-1",
        tenant_id="tenant-1",
        user_id="user-1",
        execution_requirements=(
            {"request_id": "request-1", "correlation_id": "request-1",
             "requires_agent_delegation": True}
            if requirements else None
        ),
        authorized_plan={"policy_decision_id": "policy-1"} if policy else None,
    )


@pytest.mark.asyncio
async def test_whole_plan_invokes_only_canonical_coordinator():
    request = _request()
    result = object()
    with patch(
        "ai_karen_engine.agent_medusa.coordinator.medusa_coordinator."
        "MedusaCoordinator.handle_request",
        new_callable=AsyncMock,
        return_value=result,
    ) as handle:
        actual = await MedusaLangGraphAdapter().execute_plan(request, _plan())
    assert actual is result
    handle.assert_awaited_once()
    forwarded_request = handle.await_args.args[0]
    assert forwarded_request is not request
    assert forwarded_request.authorized_plan["authorized_user_id"] == "user-1"
    assert forwarded_request.authorized_plan["authorized_tenant_id"] == "tenant-1"
    assert forwarded_request.authorized_plan["topology"] == "multi_agent"
    assert request.authorized_plan == {"policy_decision_id": "policy-1"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runtime_request", "plan", "message"),
    [
        (_request(requirements=False), _plan(), "CORTEX requirements"),
        (_request(policy=False), _plan(), "RuntimePolicy authorization"),
        (_request(), _plan(policy_decision_id="other"), "policy decision mismatch"),
        (_request(), _plan(authorized_tenant_id="other"), "execution scope mismatch"),
        (_request(), _plan(topology=ExecutionTopology.DIRECT), "multi-agent topology"),
    ],
)
async def test_invalid_plan_cannot_invoke_coordinator(runtime_request, plan, message):
    with patch(
        "ai_karen_engine.agent_medusa.coordinator.medusa_coordinator."
        "MedusaCoordinator.handle_request",
        new_callable=AsyncMock,
    ) as handle:
        with pytest.raises(PermissionError, match=message):
            await MedusaLangGraphAdapter().execute_plan(runtime_request, plan)
    handle.assert_not_awaited()


@pytest.mark.asyncio
async def test_specialist_execution_is_also_routed_through_canonical_coordinator():
    request = _request()
    result = object()
    with patch(
        "ai_karen_engine.agent_medusa.coordinator.medusa_coordinator."
        "MedusaCoordinator.handle_request",
        new_callable=AsyncMock,
        return_value=result,
    ) as handle:
        actual = await MedusaLangGraphAdapter().execute_specialist(
            request,
            _plan(),
            "analyst",
            {"question": "inspect this"},
        )

    assert actual is result
    handle.assert_awaited_once()
    forwarded_request = handle.await_args.args[0]
    assert forwarded_request.authorized_plan["allowed_agents"] == ["analyst"]
    assert forwarded_request.authorized_plan["authorized_user_id"] == "user-1"
    assert forwarded_request.authorized_plan["authorized_tenant_id"] == "tenant-1"
    assert forwarded_request.context["langgraph_specialist_input"] == {
        "question": "inspect this"
    }


@pytest.mark.asyncio
async def test_specialist_execution_refuses_agent_outside_runtime_policy():
    request = _request()
    with patch(
        "ai_karen_engine.agent_medusa.coordinator.medusa_coordinator."
        "MedusaCoordinator.handle_request",
        new_callable=AsyncMock,
    ) as handle:
        with pytest.raises(PermissionError, match="not authorized"):
            await MedusaLangGraphAdapter().execute_specialist(
                request,
                _plan(),
                "researcher",
                {"question": "inspect this"},
            )
    handle.assert_not_awaited()
