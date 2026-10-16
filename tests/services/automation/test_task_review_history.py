"""MI-10: task review events are append-only, owner-scoped and never fake success."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.automation import tasks as task_routes
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.outcome.store import (
    InMemoryOutcomeStore, OutcomeStoreError, PostgresOutcomeStore,
)
from ai_karen_engine.services.automation import execution


TENANT, OWNER, OTHER = (str(uuid4()) for _ in range(3))
TASK = "task-history-proof"
ATTEMPT = str(uuid4())


def principal(user_id=OWNER, tenant_id=TENANT):
    return UserData(user_id=user_id, tenant_id=tenant_id)


class OwnedTask:
    async def get_task(self, task_id, tenant_id, *, created_by=None):
        if task_id != TASK or tenant_id != TENANT or created_by != OWNER:
            return None
        return {"id": TASK, "created_by": OWNER, "status": "Success"}


def review_payload(*, outcome_id="out_review_1", owner=OWNER, tenant=TENANT, task=TASK):
    return {
        "outcome_id": outcome_id,
        "source": "user.feedback",
        "feedback_type": "task_completion_confirmation",
        "tenant_id": tenant,
        "user_id": owner,
        "task_id": task,
        "trajectory_id": f"task:{task}",
        "execution_id": ATTEMPT,
        "decision": "approve",
        "review_status": "Success",
        "review_note": "Reviewed",
        "reviewed_at": "2026-10-16T03:00:00+00:00",
        "recorded_at": "2026-10-16T03:00:00+00:00",
        "acceptance_criteria": "Show a real output",
        "receipt_sha256": "b" * 64,
        "correlation_id": "trace-1",
        "result_receipt": {
            "answer_text": "Original evidence survives reruns",
            "answer_truncated": False,
            "artifact_count": 0,
            "attachment_count": 0,
        },
    }


@pytest.mark.asyncio
async def test_history_preserves_reviewed_output_without_cross_user_leak(monkeypatch):
    store = InMemoryOutcomeStore()
    store.save_outcome(review_payload())
    store.save_outcome(review_payload(outcome_id="out_review_foreign", owner=OTHER))
    store.save_outcome(review_payload(outcome_id="out_review_foreign_tenant", tenant=str(uuid4())))
    store.save_outcome(review_payload(outcome_id="out_review_unrelated", task="other-task"))
    store.save_outcome({**review_payload(outcome_id="out_other_kind"), "feedback_type": "thumbs_up"})
    monkeypatch.setattr(execution, "get_outcome_store", lambda: store)

    events = await execution.list_saved_task_reviews(
        TASK, user=principal(), repository=OwnedTask(),
    )
    assert len(events) == 1
    assert events[0]["execution_id"] == ATTEMPT
    assert events[0]["result_receipt"]["answer_text"] == "Original evidence survives reruns"
    assert events[0]["human_attestation"] is True
    assert events[0]["independently_verified"] is False
    assert "tenant_id" not in events[0]
    assert "user_id" not in events[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("user", [principal(OTHER), principal(OWNER, str(uuid4()))])
async def test_cross_principal_history_fails_before_store_access(monkeypatch, user):
    class ForbiddenStore:
        async def list_task_reviews_async(self, *args, **kwargs):
            raise AssertionError("Cross-user read reached evidence store")

    monkeypatch.setattr(execution, "get_outcome_store", lambda: ForbiddenStore())
    with pytest.raises(execution.AutomationTargetNotFound):
        await execution.list_saved_task_reviews(
            TASK, user=user, repository=OwnedTask(),
        )


@pytest.mark.asyncio
async def test_missing_outcome_store_does_not_respond_with_fake_empty_history(monkeypatch):
    class BrokenStore:
        async def list_task_reviews_async(self, *args, **kwargs):
            raise OutcomeStoreError("Unreachable PostgreSQL")

    monkeypatch.setattr(execution, "get_outcome_store", lambda: BrokenStore())
    with pytest.raises(OutcomeStoreError):
        await execution.list_saved_task_reviews(
            TASK, user=principal(), repository=OwnedTask(),
        )


@pytest.mark.asyncio
async def test_history_route_propagates_owner_and_limits(monkeypatch):
    async def read(task_id, *, user, limit):
        assert task_id == TASK
        assert user.tenant_id == TENANT
        assert user.user_id == OWNER
        assert limit == 7
        data = review_payload()
        return [{
            "outcome_id": data["outcome_id"],
            "execution_id": data["execution_id"],
            "decision": data["decision"],
            "status": "Success" if data["decision"] == "approve" else "Rejected",
            "review_note": data["review_note"],
            "reviewed_at": data["reviewed_at"],
            "acceptance_criteria": data["acceptance_criteria"],
            "receipt_sha256": data["receipt_sha256"],
            "result_receipt": data["result_receipt"],
            "correlation_id": data["correlation_id"],
            "human_attestation": True,
            "independently_verified": False,
        }]

    monkeypatch.setattr(task_routes, "list_saved_task_reviews", read)
    rows = await task_routes.get_task_reviews(TASK, limit=7, user=principal())
    assert len(rows) == 1
    assert rows[0].decision == "approve"
    assert rows[0].reviewed_at == datetime(2026, 10, 16, 3, tzinfo=timezone.utc)


@pytest.mark.asyncio
@pytest.mark.parametrize(("err", "expected"), [
    (execution.AutomationTargetNotFound("hidden"), 404),
    (OutcomeStoreError("db failed"), 503),
])
async def test_history_route_is_honest_on_denials_and_outages(monkeypatch, err, expected):
    async def fail(*args, **kwargs):
        raise err

    monkeypatch.setattr(task_routes, "list_saved_task_reviews", fail)
    with pytest.raises(HTTPException) as e:
        await task_routes.get_task_reviews(TASK, limit=50, user=principal())
    assert e.value.status_code == expected


def test_transactional_outcome_append_reuses_canonical_store_contract():
    root = Path(__file__).resolve().parents[3]
    repo = (root / "src/ai_karen_engine/persistence/repositories/automation_repository.py").read_text()
    store = (root / "src/ai_karen_engine/core/runtime/outcome/store.py").read_text()
    method = repo.split("    async def review_task(", 1)[1].split("    async def task_summary(", 1)[0]
    assert "async with async_transaction_scope(tenant_id) as session:" in method
    assert "await PostgresOutcomeStore.append_in_transaction(" in method
    assert "session, review_event," in method
    assert "return _task_row(row)" in method
    assert method.index("await PostgresOutcomeStore.append_in_transaction(") < method.index("return _task_row(row)")
    assert '"result_receipt": data.get("result_receipt") or {}' in method
    assert "event_type" in method
    assert "UserFeedbackType.TASK_COMPLETION_CONFIRMATION" in method
    assert '"review_status": target' in method
    assert '"status": target' not in method.split("review_event = {", 1)[1]
    assert 'source": "user.feedback"' in method
    assert "rowcount != 1" in store
    assert "AND user_id = CAST(:user_id AS uuid)" in store
    assert "AND trajectory_id = :trajectory_id" in store
    assert "AND payload->>'task_id' = :task_id" in store


@pytest.mark.asyncio
async def test_duplicate_deterministic_receipt_id_fails_closed():
    class DuplicateSession:
        async def execute(self, statement, params):
            assert params["outcome_id"] == "out_task_review_collision"
            return type("Result", (), {"rowcount": 0})()

    with pytest.raises(OutcomeStoreError, match="not appended"):
        await PostgresOutcomeStore.append_in_transaction(
            DuplicateSession(),
            {
                "outcome_id": "out_task_review_collision",
                "tenant_id": TENANT, "user_id": OWNER,
                "source": "user.feedback",
            },
        )
