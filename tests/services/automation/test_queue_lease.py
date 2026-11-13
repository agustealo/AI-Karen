from __future__ import annotations

import asyncio

import pytest

from ai_karen_engine.services.automation.queue_lease import (
    QueueClaimLost,
    run_with_queue_claim_heartbeat,
)
from ai_karen_engine.services.database.repositories.base import RepositoryResult
from ai_karen_engine.services.database.repositories.queue_client import QueueItem


class FakeQueueClient:
    def __init__(self, renewals: list[RepositoryResult[bool]]) -> None:
        self._renewals = list(renewals)
        self.renew_calls = 0

    async def renew_claim(self, queue, item_id, claim_token=None):
        self.renew_calls += 1
        if self._renewals:
            return self._renewals.pop(0)
        return RepositoryResult(success=True, data=True)


def _item() -> QueueItem:
    return QueueItem(
        id="queue-item-1",
        queue="automation",
        claim_token="claim-token-1",
    )


@pytest.mark.asyncio
async def test_long_operation_renews_claim_until_completion():
    client = FakeQueueClient([RepositoryResult(success=True, data=True)])

    async def work():
        await asyncio.sleep(0.02)
        return "done"

    result = await run_with_queue_claim_heartbeat(
        client,
        _item(),
        work(),
        heartbeat_seconds=0.005,
    )

    assert result == "done"
    assert client.renew_calls >= 1


@pytest.mark.asyncio
async def test_lost_claim_cancels_unowned_work():
    client = FakeQueueClient([RepositoryResult(success=True, data=False)])
    cancelled = asyncio.Event()

    async def work():
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    with pytest.raises(QueueClaimLost):
        await run_with_queue_claim_heartbeat(
            client,
            _item(),
            work(),
            heartbeat_seconds=0.001,
        )

    assert client.renew_calls == 1
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_missing_claim_token_refuses_to_start_work():
    client = FakeQueueClient([])
    started = False

    async def work():
        nonlocal started
        started = True

    item = _item()
    item.claim_token = None

    with pytest.raises(QueueClaimLost):
        await run_with_queue_claim_heartbeat(
            client,
            item,
            work(),
            heartbeat_seconds=0.001,
        )

    assert started is False
    assert client.renew_calls == 0


def _scheduled_item(*, tenant_id: str = "tenant-a") -> QueueItem:
    return QueueItem(
        id="queue-item-1",
        queue="automation",
        tenant_id=tenant_id,
        claim_token="claim-token-1",
        payload={
            "cron_id": "cron-a",
            "tenant_id": "tenant-a",
            "created_by": "owner-a",
            "target_id": "task-a",
            "job_type": "Task",
            "trigger": "cron",
        },
    )


@pytest.mark.asyncio
async def test_queue_worker_rejects_cross_tenant_payload_before_principal_resolution(
    monkeypatch,
):
    from ai_karen_engine.api_routes.automation import cron

    calls = []

    async def forbidden_principal(**kwargs):
        calls.append(("principal", kwargs))
        raise AssertionError("Mismatched tenant must never resolve an owner")

    async def forbidden_execution(**kwargs):
        calls.append(("execution", kwargs))
        raise AssertionError("Mismatched tenant must never execute")

    monkeypatch.setattr(cron, "resolve_scheduled_principal", forbidden_principal)
    monkeypatch.setattr(cron, "execute_automation_target", forbidden_execution)

    with pytest.raises(RuntimeError, match="Queue tenant metadata mismatch"):
        await cron._execute_claimed_queue_item(_scheduled_item(tenant_id="tenant-b"))

    assert calls == []


@pytest.mark.asyncio
async def test_queue_worker_preserves_owner_and_cron_provenance(monkeypatch):
    from ai_karen_engine.api_routes.automation import cron

    calls = []
    principal = object()

    async def resolve(*, user_id, tenant_id):
        calls.append(("principal", user_id, tenant_id))
        return principal

    async def execute(*, job_type, target_id, user, source_id):
        calls.append(("execute", job_type, target_id, user, source_id))

    monkeypatch.setattr(cron, "resolve_scheduled_principal", resolve)
    monkeypatch.setattr(cron, "execute_automation_target", execute)

    assert await cron._execute_claimed_queue_item(_scheduled_item()) == "tenant-a"
    assert calls == [
        ("principal", "owner-a", "tenant-a"),
        ("execute", "Task", "task-a", principal, "cron-a"),
    ]


@pytest.mark.asyncio
async def test_queue_worker_revoked_owner_never_executes(monkeypatch):
    from ai_karen_engine.api_routes.automation import cron

    calls = []

    async def missing_owner(*, user_id, tenant_id):
        calls.append(("principal", user_id, tenant_id))
        raise PermissionError("Owner no longer authorized")

    async def forbidden_execution(**kwargs):
        calls.append(("execution", kwargs))
        raise AssertionError("Revoked owner cannot execute")

    monkeypatch.setattr(cron, "resolve_scheduled_principal", missing_owner)
    monkeypatch.setattr(cron, "execute_automation_target", forbidden_execution)

    with pytest.raises(PermissionError, match="Owner no longer authorized"):
        await cron._execute_claimed_queue_item(_scheduled_item())

    assert calls == [("principal", "owner-a", "tenant-a")]


@pytest.mark.asyncio
async def test_queue_worker_failed_execution_is_not_success(monkeypatch):
    from ai_karen_engine.api_routes.automation import cron

    async def resolve(*, user_id, tenant_id):
        return (user_id, tenant_id)

    async def fail_execute(*, job_type, target_id, user, source_id):
        assert user == ("owner-a", "tenant-a")
        assert source_id == "cron-a"
        raise RuntimeError("Durable task outcome unavailable")

    monkeypatch.setattr(cron, "resolve_scheduled_principal", resolve)
    monkeypatch.setattr(cron, "execute_automation_target", fail_execute)

    with pytest.raises(RuntimeError, match="Durable task outcome unavailable"):
        await cron._execute_claimed_queue_item(_scheduled_item())


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "execution_failure", "ack_failure"])
async def test_queue_worker_acknowledges_only_successful_owned_execution(
    monkeypatch, outcome,
):
    """Exercise the actual worker loop through one durable claim and shutdown."""
    from ai_karen_engine.api_routes.automation import cron

    events = []
    item = _scheduled_item()

    class OneShotQueue:
        def __init__(self):
            self.dequeues = 0

        async def dequeue(self, queue, worker_id):
            assert queue == "automation"
            self.dequeues += 1
            if self.dequeues > 1:
                raise asyncio.CancelledError()
            events.append("dequeue")
            return RepositoryResult(success=True, data=item)

        async def renew_claim(self, queue, item_id, claim_token=None):
            assert queue == "automation"
            assert item_id == item.id
            assert claim_token == item.claim_token
            return RepositoryResult(success=True, data=True)

        async def ack(self, queue, item_id, claim_token=None):
            assert (queue, item_id, claim_token) == (
                item.queue, item.id, item.claim_token,
            )
            events.append("ack")
            if outcome == "ack_failure":
                return RepositoryResult(success=False, data=False, error="claim lost")
            return RepositoryResult(success=True, data=True)

        async def nack(self, queue, item_id, error, claim_token=None):
            assert (queue, item_id, claim_token) == (
                item.queue, item.id, item.claim_token,
            )
            events.append(("nack", error))
            return RepositoryResult(success=True, data=True)

    async def resolve(*, user_id, tenant_id):
        assert (user_id, tenant_id) == ("owner-a", "tenant-a")
        events.append("principal")
        return (user_id, tenant_id)

    async def execute(*, job_type, target_id, user, source_id):
        assert (job_type, target_id, user, source_id) == (
            "Task", "task-a", ("owner-a", "tenant-a"), "cron-a",
        )
        events.append("execute")
        if outcome == "execution_failure":
            raise RuntimeError("task runtime failed")

    client = OneShotQueue()
    monkeypatch.setattr(cron, "get_queue_client", lambda: client)
    monkeypatch.setattr(cron, "resolve_scheduled_principal", resolve)
    monkeypatch.setattr(cron, "execute_automation_target", execute)

    with pytest.raises(asyncio.CancelledError):
        await cron._queue_worker_loop()

    assert events[:3] == ["dequeue", "principal", "execute"]
    assert client.dequeues == 2
    if outcome == "success":
        assert events == ["dequeue", "principal", "execute", "ack"]
    elif outcome == "execution_failure":
        assert "ack" not in events
        assert len(events) == 4
        assert events[3][0] == "nack"
        assert "task runtime failed" in events[3][1]
    else:
        assert events[3] == "ack"
        assert len(events) == 5
        assert events[4][0] == "nack"
        assert "claim lost" in events[4][1]
