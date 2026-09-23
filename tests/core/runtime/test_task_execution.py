from __future__ import annotations

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime import task_execution
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionResult,
    ChatExecutionStatus,
    ChatRuntimeMetadata,
)


@pytest.mark.asyncio
async def test_task_execution_delegates_to_chat_runtime_with_trusted_identity(monkeypatch):
    captured = {}

    class FakeRuntime:
        async def execute(self, request):
            captured["request"] = request
            return ChatExecutionResult(
                answer="completed",
                status=ChatExecutionStatus.OK,
                metadata=ChatRuntimeMetadata(
                    correlation_id=request.context.correlation_id,
                    response_source="test",
                ),
            )

    monkeypatch.setattr(task_execution, "get_chat_runtime", lambda: FakeRuntime())

    user = UserData(
        user_id="user-a",
        tenant_id="tenant-a",
        roles=["member"],
    )
    task = {
        "id": "task-1",
        "name": "Research invoices",
        "description": "Find the April invoice and summarize it.",
        "primaryAgent": "research-agent",
        "primaryAgentInstructions": "Use only authorized sources.",
        "taskType": "research",
        "subAgents": [
            {
                "name": "Verifier",
                "instructions": "Verify the source.",
                "agentId": "verification-agent",
            }
        ],
    }

    result = await task_execution.execute_task_definition(
        task,
        user=user,
        request_id="request-ingress-1",
        correlation_id="correlation-ingress-1",
    )

    assert result.answer == "completed"
    request = captured["request"]
    assert request.context.user_id == "user-a"
    assert request.context.tenant_id == "tenant-a"
    assert request.context.roles == ["member"]
    assert request.context.request_id == "request-ingress-1"
    assert request.context.correlation_id == "correlation-ingress-1"
    assert request.preferred_provider is None
    assert request.preferred_model is None
    assert request.metadata["source"] == "saved_task"
    assert request.metadata["task_definition_id"] == "task-1"
    assert request.metadata["prompt_contract"] == "task-definition.v1"
    assert request.metadata["requested_agents"] == [
        "research-agent",
        "verification-agent",
    ]
    assert request.metadata["agent_delegation"] is True
    assert request.metadata["force_graph"] is True
    assert "Find the April invoice" in request.messages[0]["content"]


@pytest.mark.asyncio
async def test_task_execution_internal_call_uses_one_fallback_identity(monkeypatch):
    captured = {}

    class FakeRuntime:
        async def execute(self, request):
            captured["request"] = request
            return ChatExecutionResult(
                answer="completed",
                status=ChatExecutionStatus.OK,
                metadata=ChatRuntimeMetadata(
                    correlation_id=request.context.correlation_id,
                ),
            )

    monkeypatch.setattr(task_execution, "get_chat_runtime", lambda: FakeRuntime())
    user = UserData(user_id="user-a", tenant_id="tenant-a")

    await task_execution.execute_task_definition(
        {
            "id": "task-1",
            "name": "x",
            "description": "y",
            "primaryAgent": "assistant",
        },
        user=user,
    )

    request = captured["request"]
    assert request.context.request_id
    assert request.context.correlation_id == request.context.request_id


@pytest.mark.asyncio
async def test_task_execution_rejects_missing_trusted_identity():
    user = UserData(user_id="", tenant_id="tenant-a")

    with pytest.raises(ValueError, match="user_id"):
        await task_execution.execute_task_definition(
            {"id": "task-1", "name": "x", "description": "y"},
            user=user,
        )

    user = UserData(user_id="user-a", tenant_id="default")
    with pytest.raises(ValueError, match="tenant_id"):
        await task_execution.execute_task_definition(
            {"id": "task-1", "name": "x", "description": "y"},
            user=user,
        )
