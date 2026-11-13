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
