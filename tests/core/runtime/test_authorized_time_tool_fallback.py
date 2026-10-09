"""Time service recovery is allowed only when the plan authorizes it."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan, ExecutionBudget, ExecutionBudgetMeter, ExecutionTopology,
)
from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionRequest, ChatExecutionContext


@pytest.mark.asyncio
async def test_time_uses_only_authorized_tool_if_plugin_unavailable():
    context = ChatExecutionContext(
        user_id="11111111-1111-1111-1111-111111111111",
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        session_id="time-test", request_id="req-time", correlation_id="corr-time",
        roles=["user"], permissions=["user"],
    )
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "What time is it?"}],
        context=context, metadata={"timezone": "America/Detroit"},
    )
    plan = AuthorizedExecutionPlan(
        execution_id="exec-time", policy_decision_id="policy-time",
        authorized_user_id=context.user_id,
        authorized_tenant_id=context.tenant_id,
        authorized_session_id=context.session_id,
        topology=ExecutionTopology.DIRECT,
        allowed_capabilities=["time_query"],
        allowed_plugins=[],
        allowed_tools=["time_tool"],
        budget=ExecutionBudget(max_duration_ms=30000, max_model_calls=1, max_tool_calls=2),
    )
    meter = ExecutionBudgetMeter(plan.budget)
    meter.start()
    decision = SimpleNamespace(
        intent="time.current", is_graph_required=False,
        policy_constraints={"direct_capability": True},
    )
    service = SimpleNamespace(
        execute_tool=AsyncMock(return_value=SimpleNamespace(
            success=True, result={"value": "8:30 AM", "status": "success"}, error=None
        ))
    )
    with patch("ai_karen_engine.core.runtime.direct_capability_executor.get_tool_service", return_value=service), patch(
        "ai_karen_engine.core.runtime.direct_capability_executor.ActionExecutionGate.authorize",
        new_callable=AsyncMock, return_value=True,
    ):
        result = await DirectCapabilityExecutor().execute(
            request=request, decision=decision, plan=plan, meter=meter
        )
    assert result.success
    assert result.source_id == "time_tool"
    assert "8:30 AM" in result.text
    assert service.execute_tool.await_count == 1
