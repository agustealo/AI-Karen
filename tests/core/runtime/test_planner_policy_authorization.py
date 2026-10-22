"""Planner reads require explicit trusted permission in RuntimePolicy."""

import pytest

from ai_karen_engine.core.runtime.policy import (
    PolicyEvaluationRequest,
    PolicyReasonCode,
    RuntimePolicyEnforcer,
)


@pytest.mark.asyncio
async def test_planner_read_denied_without_eligible_permission():
    result = await RuntimePolicyEnforcer().evaluate(
        PolicyEvaluationRequest(
            user_id="user", tenant_id="tenant", action="planner.read",
            requested_capabilities=["planner.read"], permissions=[],
        )
    )
    assert not result.allowed
    assert "planner.read" in result.denied_capabilities
    assert PolicyReasonCode.INSUFFICIENT_PERMISSION in result.reason_codes


@pytest.mark.asyncio
async def test_planner_read_authorized_permission_not_rejected_by_planner_gate():
    result = await RuntimePolicyEnforcer().evaluate(
        PolicyEvaluationRequest(
            user_id="user", tenant_id="tenant", action="planner.read",
            requested_capabilities=["planner.read"],
            permissions=["planner:read"],
        )
    )
    assert PolicyReasonCode.INSUFFICIENT_PERMISSION not in result.reason_codes
    if result.allowed:
        assert "planner.read" in result.allowed_capabilities


@pytest.mark.asyncio
async def test_unrelated_read_capability_not_conflated_with_planner_permissions():
    result = await RuntimePolicyEnforcer().evaluate(
        PolicyEvaluationRequest(
            user_id="user", tenant_id="tenant", action="time.current",
            requested_capabilities=["time_query"], permissions=[],
        )
    )
    assert "planner.read" not in result.denied_capabilities
