"""KOC-04H: channel side effects require independent RuntimePolicy permissions."""

from __future__ import annotations

import pytest

from ai_karen_engine.core.runtime.policy.runtime_policy import (
    PolicyEvaluationRequest,
    PolicyReasonCode,
    RuntimePolicyEnforcer,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["channel.send", "channel.recover"])
async def test_requested_channel_capability_without_permission_is_denied(action):
    policy = RuntimePolicyEnforcer()
    decision = await policy.evaluate(PolicyEvaluationRequest(
        user_id="principal-a",
        tenant_id="tenant-a",
        session_id="session-a",
        plugin_id="telegram-bot",
        requested_capabilities=[action],
        permissions=[],
    ))
    assert decision.allowed is False
    assert PolicyReasonCode.INSUFFICIENT_PERMISSION in decision.reason_codes
    assert action in decision.denied_capabilities
    plan = decision.to_authorized_plan()
    assert action not in plan.allowed_capabilities
    assert "telegram-bot" not in plan.allowed_plugins


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["channel.send", "channel.recover"])
async def test_trusted_permission_can_be_evaluated_without_self_grant(action):
    policy = RuntimePolicyEnforcer()
    decision = await policy.evaluate(PolicyEvaluationRequest(
        user_id="principal-a",
        tenant_id="tenant-a",
        session_id="session-a",
        plugin_id="telegram-bot",
        requested_capabilities=[action],
        permissions=[action],
    ))
    assert decision.allowed is True
    plan = decision.to_authorized_plan()
    assert plan.matches_execution_scope(
        user_id="principal-a", tenant_id="tenant-a", session_id="session-a",
    )
    assert action in plan.allowed_capabilities
    assert "telegram-bot" in plan.allowed_plugins


@pytest.mark.asyncio
async def test_recovery_permission_does_not_imply_send_permission():
    policy = RuntimePolicyEnforcer()
    decision = await policy.evaluate(PolicyEvaluationRequest(
        user_id="principal-a",
        tenant_id="tenant-a",
        plugin_id="telegram-bot",
        requested_capabilities=["channel.send", "channel.recover"],
        permissions=["channel.recover"],
    ))
    assert decision.allowed is False
    assert decision.denied_capabilities == ["channel.send"]


@pytest.mark.asyncio
async def test_unrelated_capabilities_remain_owned_by_existing_policy():
    policy = RuntimePolicyEnforcer()
    decision = await policy.evaluate(PolicyEvaluationRequest(
        user_id="principal-a",
        tenant_id="tenant-a",
        requested_capabilities=["general_assist"],
        permissions=[],
    ))
    assert decision.allowed is True
    assert decision.allowed_capabilities == ["general_assist"]
