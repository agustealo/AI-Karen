from __future__ import annotations

import asyncio

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionResult,
    ChatExecutionStatus,
    ChatRuntimeMetadata,
)
from ai_karen_engine.services.automation import execution


class FakeRepository:
    def __init__(self):
        self.completed = []

    async def mark_task_running(self, task_id, tenant_id):
        if task_id == "missing":
            return None
        return {
            "id": task_id,
            "name": "Saved task",
            "description": "Do work",
            "primaryAgent": "agent-a",
            "primaryAgentInstructions": "",
            "taskType": "saved_task",
            "subAgents": [],
            "tenant_id": tenant_id,
        }

    async def complete_task(
        self,
        task_id,
        tenant_id,
        *,
        status,
        last_error,
        runtime_task_id=None,
    ):
        record = {
            "id": task_id,
            "status": status,
            "lastError": last_error,
            "runtimeTaskId": runtime_task_id,
        }
        self.completed.append(record)
        return record


@pytest.mark.asyncio
async def test_saved_task_execution_persists_runtime_identity(monkeypatch):
    repo = FakeRepository()

    async def runtime(task, *, user, request_id=None, correlation_id=None):
        assert task["primaryAgent"] == "agent-a"
        assert user.tenant_id == "tenant-a"
        assert request_id == "request-a"
        assert correlation_id == "corr-a"
        return ChatExecutionResult(
            answer="done",
            status=ChatExecutionStatus.OK,
            metadata=ChatRuntimeMetadata(correlation_id=correlation_id),
        )

    monkeypatch.setattr(execution, "execute_task_definition", runtime)
    outcome = await execution.execute_saved_task(
        "task-a",
        user=UserData(user_id="user-a", tenant_id="tenant-a"),
        request_id="request-a",
        correlation_id="corr-a",
        repository=repo,
    )

    assert outcome.task["status"] == "Success"
    assert repo.completed[-1]["runtimeTaskId"] == "corr-a"


@pytest.mark.asyncio
async def test_saved_task_cancellation_is_terminal(monkeypatch):
    repo = FakeRepository()

    async def runtime(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(execution, "execute_task_definition", runtime)

    with pytest.raises(asyncio.CancelledError):
        await execution.execute_saved_task(
            "task-a",
            user=UserData(user_id="user-a", tenant_id="tenant-a"),
            repository=repo,
        )

    assert repo.completed[-1]["status"] == "Failed"
    assert repo.completed[-1]["lastError"] == "Task execution cancelled"
