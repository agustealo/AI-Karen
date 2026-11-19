"""Remote cancellation proves durable acceptance before Redis signalling."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
    DistributedRunNotCancellable,
    DistributedRunNotFound,
    DistributedRunStoreUnavailable,
    DistributedRunTenantMismatch,
)
from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
    DurableRunLedgerConflict,
    DurableRunLedgerUnavailable,
)
from ai_karen_engine.agent_medusa.execution.run_manager import (
    MedusaRunManager,
    RunNotCancellableError,
    RunNotFoundError,
    RunTenantMismatchError,
)
from ai_karen_engine.config.agent_medusa import AgentMedusaRuntimeSettings


class LiveLease:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.status = "running"
        self.tenant_id = "tenant-a"
        self.lease_alive = True
        self.fail_signal = False
        self.fail_get = False

    async def available(self) -> bool:
        return True

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        self.events.append("redis_get")
        if self.fail_get:
            raise DistributedRunNotFound(run_id)
        if tenant_id != self.tenant_id:
            raise DistributedRunTenantMismatch(run_id)
        return {
            "run_id": run_id,
            "status": self.status if self.lease_alive else "orphaned",
            "cancellable": self.status == "running" and self.lease_alive,
        }

    async def request_cancel(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        self.events.append("redis_cancel")
        if self.fail_signal:
            raise DistributedRunStoreUnavailable("injected Redis outage")
        if tenant_id != self.tenant_id:
            raise DistributedRunTenantMismatch(run_id)
        if self.status != "running" or not self.lease_alive:
            raise DistributedRunNotCancellable(run_id)
        self.status = "cancelling"
        return {
            "run_id": run_id,
            "status": "cancelling",
            "cancellable": False,
        }


class DurableAcceptance:
    def __init__(self, events: list[str], failure: str | None = None) -> None:
        self.events = events
        self.failure = failure
        self.received: list[dict[str, Any]] = []

    async def mark_cancelling(self, **kwargs: Any) -> None:
        self.events.append("durable_cancel")
        self.received.append(kwargs)
        if self.failure == "unavailable":
            raise DurableRunLedgerUnavailable("injected PostgreSQL outage")
        if self.failure == "conflict":
            raise DurableRunLedgerConflict("injected audit conflict")

    async def get(self, *, run_id: str, tenant_id: str) -> None:
        return None


def build_manager(
    events: list[str],
    *,
    required: bool = True,
    failure: str | None = None,
) -> tuple[MedusaRunManager, LiveLease, DurableAcceptance]:
    shared = LiveLease(events)
    durable = DurableAcceptance(events, failure)
    manager = MedusaRunManager(
        settings=AgentMedusaRuntimeSettings(
            distributed_run_control_enabled=True,
            durable_run_ledger_enabled=required,
            durable_run_ledger_required=required,
            worker_id="remote-worker",
        ),
        distributed_store=shared,
        durable_ledger=durable,
    )
    return manager, shared, durable


async def request(
    manager: MedusaRunManager, *, tenant_id: str = "tenant-a"
) -> dict[str, Any]:
    return await manager.cancel(
        run_id="remote-run",
        tenant_id=tenant_id,
        audit_event_ref="audit-original",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unavailable", "conflict"])
async def test_postgres_failure_does_not_write_redis_signal(failure: str) -> None:
    events: list[str] = []
    manager, shared, durable = build_manager(events, failure=failure)
    error = (
        DurableRunLedgerUnavailable
        if failure == "unavailable"
        else DurableRunLedgerConflict
    )
    with pytest.raises(error):
        await request(manager)

    assert events == ["redis_get", "durable_cancel"]
    assert shared.status == "running"
    assert durable.received[0]["tenant_id"] == "tenant-a"
    assert durable.received[0]["audit_event_ref"] == "audit-original"


@pytest.mark.asyncio
async def test_valid_remote_ack_requires_postgres_before_redis() -> None:
    events: list[str] = []
    manager, shared, durable = build_manager(events)

    result = await request(manager)

    assert events == ["redis_get", "durable_cancel", "redis_cancel"]
    assert result["status"] == "cancelling"
    assert result["cancellation_acknowledgement"] == "durably_accepted"
    assert result["status"] != "cancelled"
    assert shared.status == "cancelling"
    assert durable.received[0]["source"] == "admin_cancel"
    assert isinstance(durable.received[0]["requested_at"], datetime)
    assert durable.received[0]["requested_at"].tzinfo is timezone.utc


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["expired", "terminal", "missing"])
async def test_invalid_lease_is_rejected_before_postgres(state: str) -> None:
    events: list[str] = []
    manager, shared, durable = build_manager(events)
    if state == "expired":
        shared.lease_alive = False
    elif state == "terminal":
        shared.status = "completed"
    else:
        shared.fail_get = True

    with pytest.raises((RunNotCancellableError, RunNotFoundError)):
        await request(manager)

    assert events == ["redis_get"]
    assert durable.received == []


@pytest.mark.asyncio
async def test_wrong_tenant_does_not_write_any_cancellation() -> None:
    events: list[str] = []
    manager, shared, durable = build_manager(events)
    with pytest.raises(RunTenantMismatchError):
        await request(manager, tenant_id="tenant-b")
    assert events == ["redis_get"]
    assert durable.received == []
    assert shared.status == "running"


@pytest.mark.asyncio
async def test_redis_outage_after_postgres_commit_is_not_acknowledged() -> None:
    events: list[str] = []
    manager, shared, durable = build_manager(events)
    shared.fail_signal = True

    with pytest.raises(DistributedRunStoreUnavailable):
        await request(manager)

    assert events == ["redis_get", "durable_cancel", "redis_cancel"]
    assert shared.status == "running"
    assert len(durable.received) == 1


@pytest.mark.asyncio
async def test_redis_race_after_postgres_commit_does_not_claim_success() -> None:
    events: list[str] = []
    manager, shared, durable = build_manager(events)

    original = durable.mark_cancelling

    async def lose_lease(**kwargs: Any) -> None:
        await original(**kwargs)
        shared.lease_alive = False

    durable.mark_cancelling = lose_lease
    with pytest.raises(RunNotCancellableError):
        await request(manager)
    assert events == ["redis_get", "durable_cancel", "redis_cancel"]
    assert shared.status == "running"


@pytest.mark.asyncio
async def test_distributed_only_mode_identifies_redis_only_ack() -> None:
    events: list[str] = []
    manager, shared, durable = build_manager(events, required=False)
    result = await request(manager)
    assert result["cancellation_acknowledgement"] == "shared_signal_only"
    assert events == ["redis_get", "redis_cancel"]
    assert durable.received == []
