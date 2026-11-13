from __future__ import annotations

import asyncio

import pytest

from ai_karen_engine.services.automation.cron_lease import (
    CronClaimLost,
    run_with_cron_claim_heartbeat,
)


class FakeCronRepository:
    def __init__(self, renewals: list[bool]) -> None:
        self.renewals = list(renewals)
        self.calls = 0

    async def renew_cron_claim(self, cron_id, claim_token):
        self.calls += 1
        assert cron_id == "cron-a"
        assert claim_token == "claim-a"
        if self.renewals:
            return self.renewals.pop(0)
        return True


def _job():
    return {"id": "cron-a", "claim_token": "claim-a"}


@pytest.mark.asyncio
async def test_long_cron_dispatch_renews_claim_until_completion():
    repo = FakeCronRepository([True])

    async def work():
        await asyncio.sleep(0.02)
        return "done"

    result = await run_with_cron_claim_heartbeat(
        repo,
        _job(),
        work(),
        heartbeat_seconds=0.005,
    )

    assert result == "done"
    assert repo.calls >= 1


@pytest.mark.asyncio
async def test_lost_cron_claim_cancels_dispatch():
    repo = FakeCronRepository([False])
    cancelled = asyncio.Event()

    async def work():
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    with pytest.raises(CronClaimLost):
        await run_with_cron_claim_heartbeat(
            repo,
            _job(),
            work(),
            heartbeat_seconds=0.001,
        )

    assert repo.calls == 1
    assert cancelled.is_set()


def _claimed_task(*, action: str = "execute") -> dict[str, str]:
    return {
        "id": "cron-a",
        "claim_token": "claim-a",
        "tenant_id": "tenant-a",
        "created_by": "owner-a",
        "type": "Task",
        "targetId": "task-a",
        "action": action,
    }


@pytest.mark.asyncio
async def test_claimed_cron_dispatch_uses_fresh_owner_principal(monkeypatch):
    """A claimed schedule cannot execute under an inferred or client principal."""
    from ai_karen_engine.api_routes.automation import cron

    calls = []

    async def resolve(*, user_id, tenant_id):
        calls.append(("principal", user_id, tenant_id))
        return {"user_id": user_id, "tenant_id": tenant_id}

    async def execute(*, job_type, target_id, user, source_id):
        calls.append(("execute", job_type, target_id, user, source_id))

    monkeypatch.setattr(cron, "resolve_scheduled_principal", resolve)
    monkeypatch.setattr(cron, "execute_automation_target", execute)

    result = await cron._dispatch_claimed_cron(_claimed_task())

    assert result is None
    assert calls == [
        ("principal", "owner-a", "tenant-a"),
        (
            "execute",
            "Task",
            "task-a",
            {"user_id": "owner-a", "tenant_id": "tenant-a"},
            "cron-a",
        ),
    ]


@pytest.mark.asyncio
async def test_claimed_cron_fails_closed_when_fresh_owner_is_unavailable(monkeypatch):
    """A revoked or missing user cannot be replaced with a fabricated principal."""
    from ai_karen_engine.api_routes.automation import cron

    attempted = []

    async def unavailable(*, user_id, tenant_id):
        attempted.append(("principal", user_id, tenant_id))
        raise PermissionError("principal unavailable")

    async def forbidden_execution(**kwargs):
        attempted.append(("execute", kwargs))
        raise AssertionError("Task must not execute without a principal")

    monkeypatch.setattr(cron, "resolve_scheduled_principal", unavailable)
    monkeypatch.setattr(cron, "execute_automation_target", forbidden_execution)

    with pytest.raises(PermissionError, match="principal unavailable"):
        await cron._dispatch_claimed_cron(_claimed_task())

    assert attempted == [("principal", "owner-a", "tenant-a")]


@pytest.mark.asyncio
async def test_claimed_cron_enqueue_requires_durable_queue_receipt(monkeypatch):
    """A rejected enqueue is not a successful scheduled execution."""
    from ai_karen_engine.api_routes.automation import cron

    queued = []

    async def unavailable_queue(queue, payload, *, tenant_id):
        queued.append((queue, payload, tenant_id))
        return None

    async def forbidden_principal(**kwargs):
        raise AssertionError("Enqueue mode must not call the execution path")

    monkeypatch.setattr(cron, "enqueue", unavailable_queue)
    monkeypatch.setattr(cron, "resolve_scheduled_principal", forbidden_principal)

    with pytest.raises(RuntimeError, match="Durable queue enqueue failed"):
        await cron._dispatch_claimed_cron(_claimed_task(action="enqueue"))

    assert queued == [
        (
            "automation",
            {
                "cron_id": "cron-a",
                "target_id": "task-a",
                "job_type": "Task",
                "tenant_id": "tenant-a",
                "created_by": "owner-a",
                "trigger": "cron",
            },
            "tenant-a",
        ),
    ]


@pytest.mark.asyncio
async def test_claimed_cron_enqueue_returns_only_provider_receipt(monkeypatch):
    """Queue acceptance is reported as a queue ID, not task completion."""
    from ai_karen_engine.api_routes.automation import cron

    async def durable_queue(queue, payload, *, tenant_id):
        assert queue == "automation"
        assert payload["created_by"] == "owner-a"
        assert tenant_id == "tenant-a"
        return "queue-receipt-1"

    monkeypatch.setattr(cron, "enqueue", durable_queue)
    assert (
        await cron._dispatch_claimed_cron(_claimed_task(action="enqueue"))
        == "queue-receipt-1"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["cancelled", "failure", "success"])
async def test_cron_worker_interruption_preserves_due_occurrence(monkeypatch, outcome):
    """Cancellation leaves a fenced due claim for lease-expiry recovery."""
    from datetime import datetime, timezone

    from ai_karen_engine.api_routes.automation import cron

    due = {
        **_claimed_task(),
        "schedule": "0 7 * * *",
        "timezone_id": "America/Detroit",
    }
    next_instant = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    calls = []

    class OneShotRepository:
        async def claim_due_cron_jobs(self, worker_id, *, limit):
            assert limit == 1
            calls.append("claim")
            if calls.count("claim") > 1:
                raise asyncio.CancelledError()
            return [due]

        async def renew_cron_claim(self, cron_id, claim_token):
            assert (cron_id, claim_token) == ("cron-a", "claim-a")
            return True

        async def complete_cron_claim(
            self, cron_id, claim_token, *, next_run_at, last_error=None,
        ):
            calls.append(("complete", cron_id, claim_token, next_run_at, last_error))
            return True

    async def dispatch(job):
        assert job is due
        calls.append("dispatch")
        if outcome == "cancelled":
            raise asyncio.CancelledError()
        if outcome == "failure":
            raise RuntimeError("dispatch failed")

    def resolve_next(schedule, *, now, timezone_id):
        assert schedule == "0 7 * * *"
        assert timezone_id == "America/Detroit"
        assert now.tzinfo is not None
        calls.append("next_run")
        return next_instant

    monkeypatch.setattr(cron, "get_automation_repository", OneShotRepository)
    monkeypatch.setattr(cron, "_dispatch_claimed_cron", dispatch)
    monkeypatch.setattr(cron, "next_cron_run", resolve_next)

    with pytest.raises(asyncio.CancelledError):
        await cron._cron_executor_loop()

    assert calls[:2] == ["claim", "dispatch"]
    completions = [
        entry for entry in calls if isinstance(entry, tuple) and entry[0] == "complete"
    ]
    if outcome == "cancelled":
        # The existing lease expires; the original due timestamp stays due.
        assert calls == ["claim", "dispatch"]
        assert completions == []
    else:
        assert len(completions) == 1
        receipt = completions[0]
        assert receipt[1:4] == ("cron-a", "claim-a", next_instant)
        if outcome == "failure":
            assert receipt[4] == "RuntimeError: dispatch failed"
        else:
            assert receipt[4] is None
        assert calls[-1] == "claim"
