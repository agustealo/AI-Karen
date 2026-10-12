"""Medusa rejects incomplete authority envelopes before creating run records."""

from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.agent_medusa.contracts.runtime_request import RuntimeRequest
from ai_karen_engine.agent_medusa.coordinator.medusa_coordinator import (
    MedusaCoordinator,
)


def _request(
    *,
    requirements: dict | None,
    plan: dict | None = None,
) -> RuntimeRequest:
    return RuntimeRequest(
        query="perform authorized multi-agent research",
        session_id="test-session",
        request_id="test-request",
        user_id="test-user",
        tenant_id="test-tenant",
        execution_requirements=requirements,
        authorized_plan=plan or {
            "policy_decision_id": "test-policy-decision",
            "authorized_user_id": "test-user",
            "authorized_tenant_id": "test-tenant",
            "authorized_session_id": "test-session",
            "topology": "multi_agent",
        },
    )


def _requirements(**changes: object) -> dict:
    fields = {
        "request_id": "test-request",
        "correlation_id": "test-request",
        "intent": "agent.multi_agent",
        "requires_agent_delegation": True,
    }
    fields.update(changes)
    return fields


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requirements", "message"),
    [
        (None, "explicit CORTEX execution requirements"),
        (_requirements(requires_agent_delegation=False), "CORTEX-requested agent delegation"),
        (_requirements(request_id="other-request"), "request identity mismatch"),
        (_requirements(correlation_id="other-correlation"), "correlation identity mismatch"),
    ],
)
async def test_invalid_cortex_contract_creates_no_run(
    requirements: dict | None, message: str
) -> None:
    manager = AsyncMock()
    coordinator = MedusaCoordinator(run_manager=manager)

    with pytest.raises(PermissionError, match=message):
        await coordinator.handle_request(_request(requirements=requirements))

    manager.register.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plan",
    [
        {},
        {"policy_decision_id": ""},
        {"policy_decision_id": None},
    ],
)
async def test_missing_policy_decision_creates_no_run(plan: dict) -> None:
    manager = AsyncMock()
    coordinator = MedusaCoordinator(run_manager=manager)
    request = _request(requirements=_requirements(), plan=plan)
    request.authorized_plan = plan

    with pytest.raises(PermissionError, match="RuntimePolicy"):
        await coordinator.handle_request(request)

    manager.register.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"authorized_user_id": "other-user"}, "principal scope mismatch"),
        ({"authorized_tenant_id": "other-tenant"}, "principal scope mismatch"),
        ({"authorized_session_id": "other-session"}, "session scope mismatch"),
        ({"topology": "direct"}, "topology must be multi_agent"),
    ],
)
async def test_policy_scope_replay_rejected_before_registration(
    override: dict, message: str
) -> None:
    manager = AsyncMock()
    coordinator = MedusaCoordinator(run_manager=manager)
    request = _request(requirements=_requirements())
    request.authorized_plan.update(override)

    with pytest.raises(PermissionError, match=message):
        await coordinator.handle_request(request)

    manager.register.assert_not_awaited()


@pytest.mark.asyncio
async def test_distinct_correlation_id_reaches_run_ledger():
    from unittest.mock import MagicMock

    manager = AsyncMock()
    coordinator = MedusaCoordinator(run_manager=manager)
    request = _request(
        requirements=_requirements(correlation_id="trace-42"),
        plan={
            "policy_decision_id": "test-policy-decision",
            "authorized_user_id": "test-user",
            "authorized_tenant_id": "test-tenant",
            "authorized_session_id": "test-session",
            "topology": "multi_agent",
        },
    )
    request.context["execution_context"] = MagicMock(correlation_id="trace-42")
    coordinator._handle_request = AsyncMock(return_value=MagicMock())

    await coordinator.handle_request(request)

    assert manager.register.await_args.kwargs["request_id"] == "test-request"
    assert manager.register.await_args.kwargs["correlation_id"] == "trace-42"
    manager.mark_completed.assert_awaited_once_with("test-request")
