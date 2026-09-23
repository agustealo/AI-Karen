from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException, Request

from ai_karen_engine.api_routes.automation import tasks
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionResult,
    ChatExecutionStatus,
    ChatRuntimeMetadata,
)
from ai_karen_engine.services.automation.definitions import AutomationNotFoundError
from ai_karen_engine.services.automation.execution import SavedTaskExecution


def _record(task_id: str = "task-a") -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": task_id,
        "name": "Saved task",
        "description": "Do the work",
        "primaryAgent": "assistant",
        "primaryAgentInstructions": "",
        "taskType": "saved_task",
        "subAgents": [],
        "lastRun": None,
        "status": "Pending",
        "created_at": now,
        "updated_at": now,
        "lastError": None,
        "runCount": 0,
        "runtimeTaskId": None,
    }


def _request() -> Request:
    request = Request({"type": "http"})
    request.state.request_id = "request-ingress-1"
    request.state.correlation_id = "correlation-ingress-1"
    return request


class FakeDefinitions:
    async def get_task(self, task_id, *, user):
        if user.tenant_id != "tenant-a" or task_id != "task-a":
            raise AutomationNotFoundError("Task not found")
        return _record(task_id)

    async def list_tasks(self, *, user, status=None, agent_name=None):
        if user.tenant_id == "tenant-a":
            return [_record()]
        return []

    async def delete_task(self, task_id, *, user):
        if user.tenant_id != "tenant-a":
            raise AutomationNotFoundError("Task not found")


@pytest.mark.asyncio
async def test_list_tasks_delegates_tenant_scope_to_definition_authority(monkeypatch):
    monkeypatch.setattr(
        tasks,
        "get_automation_definition_service",
        lambda: FakeDefinitions(),
    )
    result = await tasks.list_tasks(
        status=None,
        agent_name=None,
        user=UserData(user_id="user-a", tenant_id="tenant-a"),
    )
    assert [task.id for task in result] == ["task-a"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get", "delete"])
async def test_cross_tenant_definition_access_is_hidden(operation, monkeypatch):
    monkeypatch.setattr(
        tasks,
        "get_automation_definition_service",
        lambda: FakeDefinitions(),
    )
    user = UserData(user_id="user-b", tenant_id="tenant-b")

    with pytest.raises(HTTPException) as exc_info:
        if operation == "get":
            await tasks.get_task("task-a", user=user)
        else:
            await tasks.delete_task("task-a", user=user)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_execute_task_preserves_ingress_identity(monkeypatch):
    async def execute(task_id, *, user, request_id=None, correlation_id=None):
        assert task_id == "task-a"
        assert user.tenant_id == "tenant-a"
        assert request_id == "request-ingress-1"
        assert correlation_id == "correlation-ingress-1"
        result = ChatExecutionResult(
            answer="real runtime result",
            status=ChatExecutionStatus.OK,
            metadata=ChatRuntimeMetadata(correlation_id=correlation_id),
        )
        record = _record(task_id)
        record["status"] = "Success"
        record["runtimeTaskId"] = correlation_id
        return SavedTaskExecution(task=record, result=result)

    monkeypatch.setattr(tasks, "execute_saved_task", execute)

    response = await tasks.execute_task(
        "task-a",
        request=_request(),
        user=UserData(user_id="user-a", tenant_id="tenant-a"),
    )

    assert response["runtime_task_id"] == "correlation-ingress-1"
    assert response["response"] == "real runtime result"
    assert response["status"] == "Success"


@pytest.mark.asyncio
async def test_execute_task_propagates_cancellation(monkeypatch):
    async def cancel(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(tasks, "execute_saved_task", cancel)

    with pytest.raises(asyncio.CancelledError):
        await tasks.execute_task(
            "task-a",
            request=_request(),
            user=UserData(user_id="user-a", tenant_id="tenant-a"),
        )
