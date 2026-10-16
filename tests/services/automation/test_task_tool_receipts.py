"""MI-12: task receipt lookup must preserve creator/attempt/run authority."""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.automation import tasks as routes
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.outcome.store import (
    InMemoryOutcomeStore, OutcomeStoreError,
)
from ai_karen_engine.services.automation import execution


TENANT = str(uuid.uuid4())
OWNER = str(uuid.uuid4())
OTHER = str(uuid.uuid4())
ATTEMPT = str(uuid.uuid4())
TASK = "my-tool-receipt-task"
REQUEST = f"task:{TASK}:request-123"


class Repository:
    def __init__(self, request_id=REQUEST):
        self.task = {
            "id": TASK,
            "created_by": OWNER,
            "status": "ReviewRequired",
            "executionId": ATTEMPT,
            "resultReceipt": {"execution_request_id": request_id},
        }

    async def get_task(self, task_id, tenant_id, *, created_by=None):
        if (
            task_id != TASK or tenant_id != TENANT
            or created_by != OWNER
        ):
            return None
        return dict(self.task)


def actor(user=OWNER, tenant=TENANT):
    return UserData(user_id=user, tenant_id=tenant)


def tool_event(*, outcome_id="receipt-a", user=OWNER, tenant=TENANT,
               trajectory=REQUEST):
    return {
        "outcome_id": outcome_id,
        "source": "runtime.execution",
        "status": "success",
        "tool_success": True,
        "trajectory_id": trajectory,
        "tenant_id": tenant,
        "user_id": user,
        "recorded_at": "2026-10-16T10:00:00+00:00",
        "metadata": {
            "event_type": "agent.tool.execution",
            "tool_call_id": "call-a",
            "tool_name": "web_search",
            "tool_version": "v2",
            "policy_decision_id": "policy-a",
            "agent_id": "researcher",
            "step_id": "step-a",
            "result_sha256": "a" * 64,
            "independently_verified": False,
        },
    }


@pytest.mark.asyncio
async def test_owner_can_read_only_exact_run_receipts(monkeypatch):
    store = InMemoryOutcomeStore()
    store.save_outcome(tool_event())
    store.save_outcome(tool_event(outcome_id="wrong-tenant", tenant=str(uuid.uuid4())))
    store.save_outcome(tool_event(outcome_id="wrong-user", user=OTHER))
    store.save_outcome(tool_event(outcome_id="wrong-run", trajectory="another-run"))
    store.save_outcome({**tool_event(outcome_id="model"), "metadata": {"event_type": "model_claim"}})
    monkeypatch.setattr(execution, "get_outcome_store", lambda: store)
    rows = await execution.list_saved_task_tool_receipts(
        TASK, user=actor(), execution_id=ATTEMPT, repository=Repository(),
    )
    assert len(rows) == 1
    assert rows[0]["receipt_id"] == "receipt-a"
    assert rows[0]["policy_decision_id"] == "policy-a"
    assert rows[0]["success"] is True
    assert rows[0]["execution_scope"] == "tool_runtime_acknowledgment"
    assert rows[0]["independently_verified"] is False
    assert "tenant_id" not in rows[0]
    assert "result" not in rows[0]


@pytest.mark.asyncio
async def test_nonowner_denied_before_outcome_store_read(monkeypatch):
    class CannotReadStore:
        async def list_governed_tool_receipts_async(self, **kwargs):
            raise AssertionError("unauthorized access reached audit store")
    monkeypatch.setattr(execution, "get_outcome_store", lambda: CannotReadStore())
    with pytest.raises(execution.AutomationTargetNotFound):
        await execution.list_saved_task_tool_receipts(
            TASK, user=actor(OTHER), execution_id=ATTEMPT, repository=Repository(),
        )
    with pytest.raises(execution.AutomationTargetNotFound):
        await execution.list_saved_task_tool_receipts(
            TASK, user=actor(tenant=str(uuid.uuid4())),
            execution_id=ATTEMPT, repository=Repository(),
        )


@pytest.mark.asyncio
async def test_stale_attempt_cannot_read_current_tool_receipts(monkeypatch):
    monkeypatch.setattr(execution, "get_outcome_store", lambda: None)
    with pytest.raises(execution.AutomationReviewConflict):
        await execution.list_saved_task_tool_receipts(
            TASK, user=actor(), execution_id=str(uuid.uuid4()),
            repository=Repository(),
        )


@pytest.mark.asyncio
async def test_legacy_task_without_proven_link_never_invents_receipts(monkeypatch):
    monkeypatch.setattr(execution, "get_outcome_store", lambda: None)
    assert await execution.list_saved_task_tool_receipts(
        TASK, user=actor(), execution_id=ATTEMPT,
        repository=Repository(request_id=None),
    ) == []


@pytest.mark.asyncio
async def test_audit_outage_propagates_instead_of_fake_empty_history(monkeypatch):
    class UnavailableStore:
        async def list_governed_tool_receipts_async(self, **kwargs):
            raise OutcomeStoreError("PostgreSQL unavailable")
    monkeypatch.setattr(execution, "get_outcome_store", lambda: UnavailableStore())
    with pytest.raises(OutcomeStoreError):
        await execution.list_saved_task_tool_receipts(
            TASK, user=actor(), execution_id=ATTEMPT, repository=Repository(),
        )


@pytest.mark.asyncio
async def test_tool_receipt_route_delegates_and_returns_typed_summary(monkeypatch):
    async def get_receipts(task_id, *, user, execution_id, limit):
        assert task_id == TASK
        assert user.user_id == OWNER
        assert execution_id == ATTEMPT
        assert limit == 11
        return [{
            "receipt_id": "receipt-a", "tool_call_id": "call-a",
            "tool_name": "web_search", "tool_version": "v2",
            "agent_id": "researcher", "step_id": "step-a",
            "policy_decision_id": "policy-a", "success": True,
            "error_type": None, "result_sha256": "a" * 64,
            "recorded_at": "2026-10-16T10:00:00+00:00",
            "execution_scope": "tool_runtime_acknowledgment",
            "independently_verified": False,
        }]
    monkeypatch.setattr(routes, "list_saved_task_tool_receipts", get_receipts)
    response = await routes.get_task_tool_receipts(
        TASK, execution_id=ATTEMPT, limit=11, user=actor(),
    )
    assert len(response) == 1
    assert response[0].success is True
    assert response[0].independently_verified is False


@pytest.mark.asyncio
@pytest.mark.parametrize(("error", "code"), [
    (execution.AutomationTargetNotFound("missing"), 404),
    (execution.AutomationReviewConflict("stale"), 409),
    (OutcomeStoreError("unavailable"), 503),
])
async def test_route_errors_fail_closed(monkeypatch, error, code):
    async def raise_error(*args, **kwargs):
        raise error
    monkeypatch.setattr(routes, "list_saved_task_tool_receipts", raise_error)
    with pytest.raises(HTTPException) as exc:
        await routes.get_task_tool_receipts(
            TASK, execution_id=ATTEMPT, limit=50, user=actor(),
        )
    assert exc.value.status_code == code
