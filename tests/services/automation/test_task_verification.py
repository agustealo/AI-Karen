"""MI-09: a model answer cannot certify a human task's completion."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.automation import tasks as routes
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionResult, ChatExecutionStatus, ChatRuntimeMetadata,
)
from ai_karen_engine.services.automation import execution


TENANT = str(uuid4())
OWNER = str(uuid4())
OTHER = str(uuid4())
ATTEMPT = str(uuid4())


def user(uid=OWNER, tenant=TENANT):
    return UserData(user_id=uid, tenant_id=tenant)


def model_result(status=ChatExecutionStatus.OK):
    return ChatExecutionResult(
        answer="The work is finished, trust me.",
        status=status,
        metadata=ChatRuntimeMetadata(
            correlation_id="corr-task",
            response_id="response-verified-by-runtime",
            assistant_message_id="assistant-persisted",
            degraded_mode=status is ChatExecutionStatus.DEGRADED,
        ),
        artifacts=[{"name": "unverified-model-claimed-file"}],
    )


class ReviewRepository:
    def __init__(self):
        self.current = {
            "id": "task-1",
            "created_by": OWNER,
            "executionId": ATTEMPT,
            "status": "ReviewRequired",
            "resultReceipt": {"answer_preview": "The work is finished, trust me."},
        }
        self.decisions = []

    async def get_task(self, task_id, tenant_id):
        if task_id != "task-1" or tenant_id != TENANT:
            return None
        return dict(self.current)

    async def review_task(self, task_id, tenant_id, *,
                          user_id, execution_id, decision, note):
        if (
            task_id != "task-1" or tenant_id != TENANT
            or user_id != OWNER or execution_id != self.current["executionId"]
            or self.current["status"] != "ReviewRequired"
        ):
            return None
        self.current["status"] = "Success" if decision == "approve" else "Rejected"
        self.current["reviewedBy"] = user_id
        self.current["reviewNote"] = note
        self.decisions.append((decision, execution_id, user_id))
        return dict(self.current)


@pytest.mark.asyncio
async def test_only_authenticated_creator_can_verify_current_attempt():
    repo = ReviewRepository()
    with pytest.raises(execution.AutomationReviewForbidden):
        await execution.review_saved_task(
            "task-1", user=user(OTHER), execution_id=ATTEMPT,
            decision="approve", repository=repo,
        )
    with pytest.raises(execution.AutomationTargetNotFound):
        await execution.review_saved_task(
            "task-1", user=user(OWNER, str(uuid4())),
            execution_id=ATTEMPT, decision="approve", repository=repo,
        )
    with pytest.raises(execution.AutomationReviewConflict):
        await execution.review_saved_task(
            "task-1", user=user(), execution_id=str(uuid4()),
            decision="approve", repository=repo,
        )
    assert repo.decisions == []
    accepted = await execution.review_saved_task(
        "task-1", user=user(), execution_id=ATTEMPT,
        decision="approve", note="Reviewed the result", repository=repo,
    )
    assert accepted["status"] == "Success"
    assert accepted["reviewedBy"] == OWNER
    with pytest.raises(execution.AutomationReviewConflict):
        await execution.review_saved_task(
            "task-1", user=user(), execution_id=ATTEMPT,
            decision="approve", repository=repo,
        )
    assert len(repo.decisions) == 1


@pytest.mark.asyncio
async def test_rejection_never_marks_completion():
    repo = ReviewRepository()
    rejected = await execution.review_saved_task(
        "task-1", user=user(), execution_id=ATTEMPT,
        decision="reject", note="No actual work product", repository=repo,
    )
    assert rejected["status"] == "Rejected"
    assert repo.decisions == [("reject", ATTEMPT, OWNER)]


@pytest.mark.asyncio
async def test_concurrent_review_compare_and_swap_allows_one_decision():
    repo = ReviewRepository()
    outcomes = await asyncio.gather(
        execution.review_saved_task(
            "task-1", user=user(), execution_id=ATTEMPT,
            decision="approve", repository=repo,
        ),
        execution.review_saved_task(
            "task-1", user=user(), execution_id=ATTEMPT,
            decision="reject", repository=repo,
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(x, dict) for x in outcomes) == 1
    assert sum(isinstance(x, execution.AutomationReviewConflict) for x in outcomes) == 1


@pytest.mark.parametrize("status", [
    ChatExecutionStatus.OK, ChatExecutionStatus.DEGRADED,
])
def test_runtime_receipts_are_observation_not_verification(status):
    receipt = execution._runtime_result_receipt(model_result(status))
    assert receipt["independently_verified"] is False
    assert receipt["runtime_status"] == status.value
    assert receipt["artifact_count"] == 1
    assert receipt["answer_preview"] == "The work is finished, trust me."
    assert receipt["response_id"] == "response-verified-by-runtime"
    assert receipt["degraded_mode"] is (status is ChatExecutionStatus.DEGRADED)


@pytest.mark.asyncio
async def test_approval_route_is_not_a_new_orchestration_path(monkeypatch):
    async def service(task_id, **kwargs):
        assert task_id == "task-1"
        assert kwargs["user"].user_id == OWNER
        assert kwargs["execution_id"] == ATTEMPT
        assert kwargs["decision"] == "approve"
        return {
            "id": "task-1", "name": "Job", "description": "Work",
            "primaryAgent": "assistant", "subAgents": [],
            "created_at": "2026-10-15T00:00:00+00:00",
            "updated_at": "2026-10-15T00:00:00+00:00",
            "status": "Success", "executionId": ATTEMPT,
        }

    monkeypatch.setattr(routes, "review_saved_task", service)
    result = await routes.review_task(
        "task-1", routes.TaskReviewRequest(
            execution_id=ATTEMPT, decision="approve",
        ), user=user(),
    )
    assert result.status == "Success"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (execution.AutomationReviewForbidden("forbidden"), 403),
        (execution.AutomationReviewConflict("stale"), 409),
        (execution.AutomationTargetNotFound("missing"), 404),
    ],
)
async def test_review_route_fail_closed(monkeypatch, error, status):
    async def denied(*args, **kwargs):
        raise error

    monkeypatch.setattr(routes, "review_saved_task", denied)
    with pytest.raises(HTTPException) as exc:
        await routes.review_task(
            "task-1", routes.TaskReviewRequest(
                execution_id=ATTEMPT, decision="approve",
            ), user=user(),
        )
    assert exc.value.status_code == status


def test_database_schema_never_grandfathers_old_model_success():
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "supabase/migrations/"
        "20261016020000_29_saved_task_completion_review.sql"
    ).read_text()
    repository = (
        root / "src/ai_karen_engine/persistence/repositories/automation_repository.py"
    ).read_text()
    assert "status = 'LegacyUnverified'" in migration
    assert "WHERE status = 'Success' AND reviewed_at IS NULL" in migration
    assert "automation_tasks_verified_receipt_check" in migration
    assert "AND created_by = CAST(:reviewer AS uuid)" in repository
    assert "AND status = 'ReviewRequired'" in repository
    assert "AND execution_id = CAST(:execution_id AS uuid)" in repository
    assert "result_receipt = CAST(:result_receipt AS jsonb)" in repository
    assert "execution_id = CAST(:claim_token AS uuid)" in repository
