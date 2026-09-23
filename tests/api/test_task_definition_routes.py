from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.automation import tasks
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionResult,
    ChatExecutionStatus,
    ChatRuntimeMetadata,
)


def _task(task_id: str, tenant_id: str) -> dict:
    now = datetime.utcnow()
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
        "created_by": f"owner-{tenant_id}",
        "tenant_id": tenant_id,
    }


@pytest.fixture(autouse=True)
def isolate_task_registry():
    tasks._tasks_db.clear()
    yield
    tasks._tasks_db.clear()


@pytest.mark.asyncio
async def test_list_tasks_is_tenant_scoped():
    tasks._tasks_db["task-a"] = _task("task-a", "tenant-a")
    tasks._tasks_db["task-b"] = _task("task-b", "tenant-b")

    result = await tasks.list_tasks(
        status=None,
        agent_name=None,
        user=UserData(user_id="user-a", tenant_id="tenant-a"),
    )

    assert [task.id for task in result] == ["task-a"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get", "delete", "execute"])
async def test_cross_tenant_task_access_is_hidden(operation, monkeypatch):
    tasks._tasks_db["task-b"] = _task("task-b", "tenant-b")
    user = UserData(user_id="user-a", tenant_id="tenant-a")

    if operation == "get":
        call = lambda: tasks.get_task("task-b", user=user)
    elif operation == "delete":
        call = lambda: tasks.delete_task("task-b", user=user)
    else:
        async def must_not_execute(*args, **kwargs):
            raise AssertionError("cross-tenant execution reached runtime")

        monkeypatch.setattr(tasks, "execute_task_definition", must_not_execute)
        call = lambda: tasks.execute_task("task-b", user=user)

    with pytest.raises(HTTPException) as exc_info:
        await call()

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_execute_task_uses_canonical_runtime_result(monkeypatch):
    tasks._tasks_db["task-a"] = _task("task-a", "tenant-a")
    user = UserData(user_id="user-a", tenant_id="tenant-a")

    async def execute(task, *, user):
        assert task["tenant_id"] == "tenant-a"
        assert user.tenant_id == "tenant-a"
        return ChatExecutionResult(
            answer="real runtime result",
            status=ChatExecutionStatus.OK,
            metadata=ChatRuntimeMetadata(correlation_id="corr-1"),
        )

    monkeypatch.setattr(tasks, "execute_task_definition", execute)

    response = await tasks.execute_task("task-a", user=user)

    task = tasks._tasks_db["task-a"]
    assert response["runtime_task_id"] == "corr-1"
    assert response["response"] == "real runtime result"
    assert task["status"] == "Success"
    assert task["runCount"] == 1
    assert task["runtimeTaskId"] == "corr-1"


@pytest.mark.asyncio
async def test_execute_exception_never_leaves_task_running(monkeypatch):
    tasks._tasks_db["task-a"] = _task("task-a", "tenant-a")
    user = UserData(user_id="user-a", tenant_id="tenant-a")

    async def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(tasks, "execute_task_definition", explode)

    with pytest.raises(HTTPException) as exc_info:
        await tasks.execute_task("task-a", user=user)

    assert exc_info.value.status_code == 500
    task = tasks._tasks_db["task-a"]
    assert task["status"] == "Failed"
    assert task["lastError"] == "RuntimeError"
    assert task["runCount"] == 1
