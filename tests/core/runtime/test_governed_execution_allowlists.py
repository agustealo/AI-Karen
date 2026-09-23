from __future__ import annotations

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.decision_pipeline import RuntimeDecisionPipeline
from ai_karen_engine.core.runtime.execution_decision import (
    ExecutionDecision,
    ExecutionTopology,
    RuntimeExecutionMode,
)
from ai_karen_engine.core.runtime.policy import RuntimePolicyEnforcer


def _request() -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "Execute the saved task."}],
        context=ChatExecutionContext(
            user_id="user-a",
            tenant_id="tenant-a",
            session_id="task:task-1",
            conversation_id="task:task-1",
            request_id="request-1",
            correlation_id="correlation-1",
            roles=["member"],
        ),
        metadata={
            "requested_agents": ["research-agent", "verification-agent"],
            "agent_delegation": True,
            "force_graph": True,
        },
    )


def _cognitive() -> ExecutionDecision:
    return ExecutionDecision(
        execution_mode=RuntimeExecutionMode.GRAPH,
        graph_required=True,
        topology=ExecutionTopology.MULTI_AGENT,
        intent="saved_task",
        requires_agent_delegation=True,
        tool_requirements=["search"],
        plugin_candidates=["source-verifier"],
        max_steps=4,
        max_model_calls=4,
        policy_constraints={"risk_signals": {}},
    )


@pytest.mark.asyncio
async def test_runtime_policy_authorizes_requested_agents_as_typed_constraints():
    pipeline = RuntimeDecisionPipeline.__new__(RuntimeDecisionPipeline)
    pipeline._policy = RuntimePolicyEnforcer()

    policy = await pipeline._evaluate_execution_policy(_request(), _cognitive())

    assert policy.allowed is True
    assert policy.runtime_constraints["allowed_agents"] == [
        "research-agent",
        "verification-agent",
    ]
    assert policy.runtime_constraints["allowed_tools"] == ["search"]
    assert policy.runtime_constraints["allowed_plugins"] == ["source-verifier"]

    plan = policy.to_authorized_plan()
    assert plan.allowed_agents == ["research-agent", "verification-agent"]
    assert plan.allowed_tools == ["search"]
    assert plan.allowed_plugins == ["source-verifier"]
    assert plan.authorized_user_id == "user-a"
    assert plan.authorized_tenant_id == "tenant-a"


@pytest.mark.asyncio
async def test_policy_allowlists_survive_decision_and_chat_plan_boundary():
    pipeline = RuntimeDecisionPipeline.__new__(RuntimeDecisionPipeline)
    pipeline._policy = RuntimePolicyEnforcer()
    request = _request()
    cognitive = _cognitive()

    policy = await pipeline._evaluate_execution_policy(request, cognitive)
    decision = pipeline._apply_execution_policy(cognitive, policy)

    assert decision.policy_constraints["allowed_agents"] == [
        "research-agent",
        "verification-agent",
    ]
    assert decision.policy_constraints["allowed_tools"] == ["search"]
    assert decision.policy_constraints["allowed_plugins"] == ["source-verifier"]

    runtime = ChatRuntime.__new__(ChatRuntime)
    plan = runtime._build_authorized_plan(request, decision)

    assert plan.allowed_agents == ["research-agent", "verification-agent"]
    assert plan.allowed_tools == ["search"]
    assert plan.allowed_plugins == ["source-verifier"]
    assert plan.authorized_user_id == "user-a"
    assert plan.authorized_tenant_id == "tenant-a"
    assert plan.authorized_session_id == "task:task-1"
