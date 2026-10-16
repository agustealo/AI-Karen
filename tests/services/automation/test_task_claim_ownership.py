"""MI-08: saved-task claims are fenced and never become fabricated success."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.automation import tasks as task_routes
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionResult,
    ChatExecutionStatus,
    ChatRuntimeMetadata,
)
from ai_karen_engine.services.automation import execution


class ClaimRepository:
    """Deterministic test model of the PostgreSQL claim CAS."""
    def __init__(self) -> None:
        self.owner = None
        self.running = False
        self.run_count = 0
        self.completed = []
        self.fail_renew = False
        self.reject_completion = False

    async def get_task(self, task_id, tenant_id):
        if tenant_id != "tenant-a" or task_id != "task-a":
            return None
        return {"id": task_id, "status": "Running" if self.running else "Pending"}

    async def mark_task_running(
        self, task_id, tenant_id, *, claim_token, lease_seconds,
    ):
        if await self.get_task(task_id, tenant_id) is None or self.running:
            return None
        self.owner = claim_token
        self.running = True
        self.run_count += 1
        return {
            "id": task_id,
            "name": "Task",
            "description": "Produce a real result",
            "primaryAgent": "assistant",
            "taskType": "saved_task",
            "subAgents": [],
        }

    async def renew_task_claim(
        self, task_id, tenant_id, *, claim_token, lease_seconds,
    ):
        return self.running and self.owner == claim_token and not self.fail_renew

    async def complete_task(
        self, task_id, tenant_id, *, claim_token, status,
        last_error, runtime_task_id=None,
    ):
        if (
            not self.running or self.owner != claim_token
            or self.reject_completion
        ):
            return None
        self.running = False
        self.owner = None
        result = {
            "id": task_id,
            "status": status,
            "lastError": last_error,
            "runtimeTaskId": runtime_task_id,
        }
        self.completed.append(result)
        return result


def user(tenant="tenant-a"):
    return UserData(user_id="user-a", tenant_id=tenant)


def runtime_result(*, status=ChatExecutionStatus.OK, answer="real response"):
    return ChatExecutionResult(
        answer=answer, status=status,
        metadata=ChatRuntimeMetadata(correlation_id="trace-1"),
    )


@pytest.mark.asyncio
async def test_only_one_live_worker_can_execute_a_saved_task(monkeypatch):
    repo = ClaimRepository()
    started, release = asyncio.Event(), asyncio.Event()
    invocations = []

    async def fake_runtime(task, *, user, request_id, correlation_id):
        invocations.append(task["id"])
        started.set()
        await release.wait()
        return runtime_result()

    monkeypatch.setattr(execution, "execute_task_definition", fake_runtime)
    first = asyncio.create_task(
        execution.execute_saved_task("task-a", user=user(), repository=repo)
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        with pytest.raises(execution.AutomationTaskBusy):
            await execution.execute_saved_task(
                "task-a", user=user(), repository=repo
            )
        assert invocations == ["task-a"]
        assert repo.run_count == 1
    finally:
        release.set()
    completed = await first
    assert completed.task["status"] == "Success"
    assert len(repo.completed) == 1
    assert repo.owner is None


@pytest.mark.asyncio
async def test_lost_lease_interrupts_execution_without_success(monkeypatch):
    repo = ClaimRepository()
    started, cancelled = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(
        execution, "get_runtime_settings",
        lambda: SimpleNamespace(timeouts=SimpleNamespace(
            saved_task_claim_lease_seconds=30,
            saved_task_claim_heartbeat_seconds=1,
        )),
    )

    async def fake_runtime(*_args, **_kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(execution, "execute_task_definition", fake_runtime)
    attempt = asyncio.create_task(
        execution.execute_saved_task("task-a", user=user(), repository=repo)
    )
    await asyncio.wait_for(started.wait(), timeout=10)
    repo.fail_renew = True
    with pytest.raises(execution.AutomationTaskClaimLost):
        await asyncio.wait_for(attempt, timeout=10)
    assert cancelled.is_set()
    assert repo.completed == []


@pytest.mark.asyncio
async def test_stale_completion_is_not_published_as_success(monkeypatch):
    repo = ClaimRepository()
    repo.reject_completion = True

    async def fake_runtime(*_args, **_kwargs):
        return runtime_result()

    monkeypatch.setattr(execution, "execute_task_definition", fake_runtime)
    with pytest.raises(execution.AutomationTaskClaimLost):
        await execution.execute_saved_task("task-a", user=user(), repository=repo)
    assert repo.completed == []


@pytest.mark.asyncio
async def test_fenced_executor_hides_foreign_tenant_task(monkeypatch):
    repo = ClaimRepository()

    async def forbidden_runtime(*_args, **_kwargs):
        raise AssertionError("unauthorized task must never be executed")

    monkeypatch.setattr(execution, "execute_task_definition", forbidden_runtime)
    with pytest.raises(execution.AutomationTargetNotFound):
        await execution.execute_saved_task(
            "task-a", user=user("tenant-b"), repository=repo
        )
    assert repo.run_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (execution.AutomationTaskBusy("busy"), 409),
        (execution.AutomationTaskClaimLost("lost"), 409),
    ],
)
async def test_execute_route_distinguishes_claim_conflicts(monkeypatch, exc, code):
    async def failed(*_args, **_kwargs):
        raise exc

    monkeypatch.setattr(task_routes, "execute_saved_task", failed)
    from fastapi import Request

    with pytest.raises(HTTPException) as raised:
        await task_routes.execute_task(
            "task-a", request=Request({"type": "http"}), user=user()
        )
    assert raised.value.status_code == code


def test_sql_claims_are_atomic_scoped_and_fenced():
    root = Path(__file__).resolve().parents[3]
    repository = (
        root / "src/ai_karen_engine/persistence/repositories/automation_repository.py"
    ).read_text(encoding="utf-8")
    migration = (
        root / "supabase/migrations/"
        "20261016010000_28_automation_task_fenced_claims.sql"
    ).read_text(encoding="utf-8")

    for field in ("claim_token uuid", "claim_expires_at timestamptz"):
        assert field in migration
    assert "ALTER TABLE public.automation_tasks" in migration
    assert "CREATE TABLE" not in migration

    mark = repository.split("    async def mark_task_running(", 1)[1].split(
        "    async def renew_task_claim(", 1
    )[0]
    renew = repository.split("    async def renew_task_claim(", 1)[1].split(
        "    async def complete_task(", 1
    )[0]
    finish = repository.split("    async def complete_task(", 1)[1].split(
        "    async def task_summary(", 1
    )[0]
    assert "UPDATE public.automation_tasks" in mark
    assert "status <> 'Running'" in mark
    assert "claim_expires_at <= now()" in mark
    assert "claim_token IS NOT NULL" in mark
    assert "run_count = run_count + 1" in mark
    for statement in (renew, finish):
        assert "tenant_id = CAST(:tenant_id AS uuid)" in statement
        assert "claim_token = CAST(:claim_token AS uuid)" in statement
        assert "claim_expires_at > now()" in statement
    assert "claim_token = NULL" in finish
    assert "claim_expires_at = NULL" in finish


def test_invalid_task_lease_configuration_fails_closed():
    from ai_karen_engine.config.runtime import RuntimeSettings

    settings = RuntimeSettings()
    settings.timeouts.saved_task_claim_lease_seconds = 30
    settings.timeouts.saved_task_claim_heartbeat_seconds = 15
    assert any("Saved task heartbeat" in value for value in settings.validate())
