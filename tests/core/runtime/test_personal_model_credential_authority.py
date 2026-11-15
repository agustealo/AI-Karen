"""Personal model API keys require host-verified grants, not request hints."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.contracts import ExecutionTopology
from ai_karen_engine.core.runtime.policy.runtime_policy import (
    PolicyEvaluationRequest,
    PolicyReasonCode,
    ProviderConstraints,
    RuntimePolicyEnforcer,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claimed_permissions",
    [
        [],
        ["model.personal_key.execute"],
        ["admin", "model.personal_key.execute"],
    ],
)
async def test_untrusted_policy_request_cannot_mint_personal_model_key_grant(
    claimed_permissions: list[str],
) -> None:
    decision = await RuntimePolicyEnforcer().evaluate(
        PolicyEvaluationRequest(
            user_id="user-1",
            tenant_id="tenant-1",
            session_id="session-1",
            permissions=claimed_permissions,
            requested_capabilities=["network_access", "model.personal_key.execute"],
            provider_constraints=ProviderConstraints(
                eligible_providers=["openai"],
                forbidden_providers=[],
                local_only=False,
                external_allowed=True,
            ),
        )
    )
    assert decision.allowed is False
    assert decision.reason_codes == [PolicyReasonCode.INSUFFICIENT_PERMISSION]
    assert decision.denied_capabilities == ["model.personal_key.execute"]
    assert "model.personal_key.execute" not in decision.to_authorized_plan().allowed_capabilities


@pytest.mark.asyncio
async def test_ordinary_policy_capability_remains_available() -> None:
    decision = await RuntimePolicyEnforcer().evaluate(
        PolicyEvaluationRequest(
            user_id="user-1",
            tenant_id="tenant-1",
            requested_capabilities=["network_access"],
        )
    )
    assert decision.allowed is True
    assert decision.to_authorized_plan().allowed_capabilities == ["network_access"]


def test_cognitive_decision_cannot_inject_personal_key_into_chat_plan() -> None:
    context = ChatExecutionContext(
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        correlation_id="corr-1",
    )
    request = ChatExecutionRequest(messages=[], context=context)
    decision = SimpleNamespace(
        time_budget_ms=1000,
        max_model_calls=1,
        tool_requirements=[],
        max_steps=1,
        execution_mode=SimpleNamespace(value="normal"),
        policy_reason_codes=[],
        risk_level=SimpleNamespace(value="low"),
        required_capabilities=["network_access", "model.personal_key.execute"],
        memory_write_allowed=False,
        policy_constraints={
            "allowed_tools": [],
            "allowed_plugins": [],
            "allowed_agents": [],
            "personal_model_credential": {
                "provider_id": "openai",
                "model_id": "selected",
                "credential_id": "untrusted",
            },
        },
        plugin_candidates=[],
        policy_decision_id="policy-1",
        topology=ExecutionTopology.DIRECT,
        memory_scope="session",
        reasoning_modes=[],
        workflow_id=None,
        intent="chat",
        reason_codes=[],
    )
    plan = ChatRuntime._build_authorized_plan(None, request, decision)
    assert plan.allowed_capabilities == ["network_access"]
    assert plan.provider_constraints == {}
    assert plan.matches_execution_scope(
        user_id="user-1", tenant_id="tenant-1", session_id="session-1"
    )
