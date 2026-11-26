from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
    DistributedRunNotCancellable,
    DistributedRunNotFound,
    DistributedRunOwnershipLost,
    DistributedRunStoreUnavailable,
    DistributedRunTenantMismatch,
    RedisDistributedRunStore,
)
from ai_karen_engine.agent_medusa.execution.run_manager import MedusaRunManager
from ai_karen_engine.config.agent_medusa import AgentMedusaRuntimeSettings


class SharedFakeRunStore:
    """Deterministic shared-store double for cross-worker behavior tests."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.available_state = True

    async def available(self) -> bool:
        return self.available_state

    async def register(
        self,
        *,
        run_id: str,
        correlation_id: str,
        tenant_id: str,
        user_id: str,
        worker_id: str,
        started_at: datetime,
    ) -> None:
        existing = self.records.get(run_id)
        if existing and self._snapshot(existing)["status"] in {"running", "cancelling"}:
            raise RuntimeError("already active")
        self.records[run_id] = {
            "run_id": run_id,
            "correlation_id": correlation_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "worker_id": worker_id,
            "status": "running",
            "started_at": started_at.isoformat(),
            "completed_at": None,
            "error_type": None,
            "cancel_requested": False,
            "lease_expires_at": datetime.now(timezone.utc) + timedelta(seconds=30),
        }

    async def heartbeat(self, *, run_id: str, worker_id: str) -> bool:
        record = self.records[run_id]
        if record["worker_id"] != worker_id:
            raise RuntimeError("ownership changed")
        if self._snapshot(record)["status"] == "orphaned":
            raise RuntimeError("ownership expired")
        record["lease_expires_at"] = datetime.now(timezone.utc) + timedelta(seconds=30)
        return bool(record["cancel_requested"])

    async def mark_terminal(
        self,
        *,
        run_id: str,
        worker_id: str,
        status: str,
        completed_at: datetime,
        error_type: str | None,
    ) -> None:
        record = self.records[run_id]
        if record["worker_id"] != worker_id:
            raise RuntimeError("ownership changed")
        record["status"] = status
        record["completed_at"] = completed_at.isoformat()
        record["error_type"] = error_type

    async def request_cancel(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        record = self.records.get(run_id)
        if record is None:
            raise DistributedRunNotFound(run_id)
        if record["tenant_id"] != tenant_id:
            raise DistributedRunTenantMismatch(run_id)
        snapshot = self._snapshot(record)
        if not snapshot["cancellable"]:
            raise DistributedRunNotCancellable(run_id)
        record["status"] = "cancelling"
        record["cancel_requested"] = True
        return self._snapshot(record)

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        record = self.records.get(run_id)
        if record is None:
            raise DistributedRunNotFound(run_id)
        if record["tenant_id"] != tenant_id:
            raise DistributedRunTenantMismatch(run_id)
        return self._snapshot(record)

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool,
    ) -> list[dict[str, Any]]:
        snapshots = [
            self._snapshot(record)
            for record in self.records.values()
            if record["tenant_id"] == tenant_id
        ]
        return [
            snapshot
            for snapshot in snapshots
            if include_terminal
            or snapshot["status"] in {"running", "cancelling", "orphaned"}
        ]

    def _snapshot(self, record: dict[str, Any]) -> dict[str, Any]:
        lease_alive = record["lease_expires_at"] > datetime.now(timezone.utc)
        status = record["status"]
        if status in {"running", "cancelling"} and not lease_alive:
            status = "orphaned"
        return {
            "run_id": record["run_id"],
            "correlation_id": record["correlation_id"],
            "tenant_id": record["tenant_id"],
            "user_id": record["user_id"],
            "status": status,
            "started_at": record["started_at"],
            "completed_at": record["completed_at"],
            "error_type": record["error_type"],
            "cancellable": status == "running" and lease_alive,
            "distributed_control": {"supported": True, "lease_alive": lease_alive},
        }


def _settings(worker_id: str) -> AgentMedusaRuntimeSettings:
    return AgentMedusaRuntimeSettings(
        distributed_run_control_enabled=True,
        run_lease_ttl_seconds=3,
        run_heartbeat_interval_seconds=1,
        run_terminal_retention_seconds=30,
        run_key_prefix="test:medusa:runs",
        worker_id=worker_id,
    )


def test_remote_worker_cancel_reaches_actual_owner_task() -> None:
    async def scenario() -> None:
        store = SharedFakeRunStore()
        owner = MedusaRunManager(
            settings=_settings("worker-a"),
            distributed_store=store,
        )
        remote = MedusaRunManager(
            settings=_settings("worker-b"),
            distributed_store=store,
        )
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def workload() -> None:
            started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(workload())
        await started.wait()
        await owner.register(
            run_id="distributed-run-1",
            correlation_id="corr-1",
            tenant_id="tenant-a",
            user_id="user-a",
            task=task,
        )

        observed = await remote.get(run_id="distributed-run-1", tenant_id="tenant-a")
        assert observed["status"] == "running"
        assert observed["cancellable"] is True

        cancelling = await remote.cancel(
            run_id="distributed-run-1",
            tenant_id="tenant-a",
        )
        assert cancelling["status"] == "cancelling"
        assert cancelling["cancellable"] is False

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2.5)
        assert cancelled.is_set()

        await owner.mark_cancelled("distributed-run-1")
        terminal = await remote.get(
            run_id="distributed-run-1",
            tenant_id="tenant-a",
        )
        assert terminal["status"] == "cancelled"

    asyncio.run(scenario())


def test_distributed_run_visibility_and_cancel_remain_tenant_scoped() -> None:
    async def scenario() -> None:
        store = SharedFakeRunStore()
        owner = MedusaRunManager(
            settings=_settings("worker-a"),
            distributed_store=store,
        )
        remote = MedusaRunManager(
            settings=_settings("worker-b"),
            distributed_store=store,
        )
        task = asyncio.create_task(asyncio.sleep(60))
        await owner.register(
            run_id="distributed-run-2",
            correlation_id="corr-2",
            tenant_id="tenant-a",
            user_id="user-a",
            task=task,
        )

        with pytest.raises(PermissionError):
            await remote.get(run_id="distributed-run-2", tenant_id="tenant-b")
        with pytest.raises(PermissionError):
            await remote.cancel(run_id="distributed-run-2", tenant_id="tenant-b")
        assert await remote.list_runs(tenant_id="tenant-b") == []

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await owner.mark_cancelled("distributed-run-2")

    asyncio.run(scenario())


def test_expired_shared_lease_becomes_orphaned_and_not_cancellable() -> None:
    async def scenario() -> None:
        store = SharedFakeRunStore()
        store.records["orphan-1"] = {
            "run_id": "orphan-1",
            "correlation_id": "corr-orphan",
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "worker_id": "dead-worker",
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "error_type": None,
            "cancel_requested": False,
            "lease_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        }
        remote = MedusaRunManager(
            settings=_settings("worker-b"),
            distributed_store=store,
        )

        snapshot = await remote.get(run_id="orphan-1", tenant_id="tenant-a")
        assert snapshot["status"] == "orphaned"
        assert snapshot["cancellable"] is False
        with pytest.raises(RuntimeError):
            await remote.cancel(run_id="orphan-1", tenant_id="tenant-a")

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["unavailable", "conflict"])
def test_remote_cancel_waits_for_required_durable_transition(failure: str) -> None:
    """Redis request alone must not cancel the owner's task when PostgreSQL fails."""

    from dataclasses import replace

    from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
        DurableRunLedgerConflict,
        DurableRunLedgerUnavailable,
    )
    from ai_karen_engine.agent_medusa.execution.run_manager import ExecutionRunStatus

    class FlakyCancellationLedger:
        def __init__(self) -> None:
            self.available = False
            self.attempts = 0

        async def mark_cancelling(self, **kwargs: Any) -> None:
            self.attempts += 1
            if not self.available:
                if failure == "unavailable":
                    raise DurableRunLedgerUnavailable("injected postgres outage")
                raise DurableRunLedgerConflict("injected durable conflict")

    async def scenario() -> None:
        shared = SharedFakeRunStore()
        owner = MedusaRunManager(
            settings=_settings("worker-a"),
            distributed_store=shared,
        )
        remote = MedusaRunManager(
            settings=_settings("worker-b"),
            distributed_store=shared,
        )
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def workload() -> None:
            started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(workload())
        await started.wait()
        run = await owner.register(
            run_id="required-remote-cancel",
            correlation_id="corr-required",
            tenant_id="tenant-a",
            user_id="owner-a",
            task=task,
        )
        ledger = FlakyCancellationLedger()
        run.durable_registered = True
        owner._durable_ledger = ledger
        owner._settings = replace(
            owner._settings,
            durable_run_ledger_enabled=True,
            durable_run_ledger_required=True,
        )
        try:
            response = await remote.cancel(
                run_id="required-remote-cancel",
                tenant_id="tenant-a",
            )
            assert response["status"] == "cancelling"

            async def wait_for_attempt() -> None:
                while ledger.attempts == 0:
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(wait_for_attempt(), timeout=2.5)
            assert run.status is ExecutionRunStatus.RUNNING
            assert not task.cancelling()
            assert not cancelled.is_set()

            ledger.available = True
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=2.5)
            assert cancelled.is_set()
            assert ledger.attempts >= 2
        finally:
            if not task.done():
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

    asyncio.run(scenario())


class _RecoveryLedger:
    """Deterministic durable state observed only by the live owner heartbeat."""

    def __init__(
        self,
        *,
        status: str = "cancellation_requested",
        owner_worker_id: str = "worker-a",
        tenant_id: str = "tenant-a",
        fail_read: bool = False,
        slow_read: bool = False,
    ) -> None:
        self.status = status
        self.owner_worker_id = owner_worker_id
        self.tenant_id = tenant_id
        self.fail_read = fail_read
        self.slow_read = slow_read
        self.reads = 0
        self.acceptance_attempts = 0

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
            DurableRunLedgerUnavailable,
        )

        from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
            _canonical_tenant_id,
        )

        self.reads += 1
        if self.fail_read:
            raise DurableRunLedgerUnavailable("injected PostgreSQL outage")
        if self.slow_read:
            await asyncio.sleep(60)
        return {
            "run_id": run_id,
            "tenant_id": _canonical_tenant_id(self.tenant_id),
            "status": self.status,
            "owner_worker_id": self.owner_worker_id,
            "audit_event_ref": "original-remote-audit",
        }

    async def mark_cancelling(self, **kwargs: Any) -> None:
        self.acceptance_attempts += 1
        assert kwargs["source"] == "runtime"
        assert kwargs.get("audit_event_ref") is None


@pytest.mark.asyncio
async def test_owner_recovers_postgres_accepted_cancel_after_lost_redis_signal() -> None:
    """The owner may retry the Redis signal only after its lease renews."""

    from dataclasses import replace

    store = SharedFakeRunStore()
    owner = MedusaRunManager(
        settings=_settings("worker-a"),
        distributed_store=store,
    )
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def workload() -> None:
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = asyncio.create_task(workload())
    ledger = _RecoveryLedger()
    try:
        await started.wait()
        run = await owner.register(
            run_id="durable-only-request",
            correlation_id="corr-durable-recovery",
            tenant_id="tenant-a",
            user_id="user-a",
            task=task,
        )
        assert store.records[run.run_id]["status"] == "running"
        assert store.records[run.run_id]["cancel_requested"] is False

        run.durable_registered = True
        owner._durable_ledger = ledger
        owner._settings = replace(
            owner._settings,
            durable_run_ledger_enabled=True,
            durable_run_ledger_required=True,
        )
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=3.5)

        assert cancelled.is_set()
        assert store.records[run.run_id]["status"] == "cancelling"
        assert store.records[run.run_id]["cancel_requested"] is True
        assert ledger.reads >= 1
        assert ledger.acceptance_attempts == 1
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "worker_id", "tenant_id", "outage"),
    [
        ("running", "worker-a", "tenant-a", False),
        ("cancelled", "worker-a", "tenant-a", False),
        ("cancellation_requested", "other-worker", "tenant-a", False),
        ("cancellation_requested", "worker-a", "other-tenant", False),
        ("cancellation_requested", "worker-a", "tenant-a", True),
    ],
)
async def test_owner_never_recovers_unproven_durable_cancel(
    status: str,
    worker_id: str,
    tenant_id: str,
    outage: bool,
) -> None:
    """Wrong ownership, tenant, status, or unavailable DB cannot cancel a task."""

    from dataclasses import replace

    store = SharedFakeRunStore()
    owner = MedusaRunManager(
        settings=_settings("worker-a"),
        distributed_store=store,
    )
    ledger = _RecoveryLedger(
        status=status,
        owner_worker_id=worker_id,
        tenant_id=tenant_id,
        fail_read=outage,
    )
    task = asyncio.create_task(asyncio.sleep(60))
    run = None
    try:
        run = await owner.register(
            run_id="not-proven-durable-cancel",
            correlation_id="corr-not-proven",
            tenant_id="tenant-a",
            user_id="user-a",
            task=task,
        )
        run.durable_registered = True
        owner._durable_ledger = ledger
        owner._settings = replace(
            owner._settings,
            durable_run_ledger_enabled=True,
            durable_run_ledger_required=True,
        )
        async def observed() -> None:
            while ledger.reads == 0:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(observed(), timeout=2.5)
        assert not task.cancelling()
        assert not task.done()
        assert store.records[run.run_id]["status"] == "running"
        assert store.records[run.run_id]["cancel_requested"] is False
        assert ledger.acceptance_attempts == 0
    finally:
        if run is not None and run.heartbeat_task is not None:
            run.heartbeat_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await run.heartbeat_task
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_durable_recovery_requires_redis_atomic_live_acceptance() -> None:
    """An expired lease after the durable read must not terminate the owner task."""

    from dataclasses import replace

    store = SharedFakeRunStore()
    owner = MedusaRunManager(
        settings=_settings("worker-a"),
        distributed_store=store,
    )
    ledger = _RecoveryLedger()
    original_request_cancel = store.request_cancel

    async def lose_ownership(*, run_id: str, tenant_id: str) -> dict[str, Any]:
        store.records[run_id]["lease_expires_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )
        return await original_request_cancel(run_id=run_id, tenant_id=tenant_id)

    store.request_cancel = lose_ownership
    task = asyncio.create_task(asyncio.sleep(60))
    run = None
    try:
        run = await owner.register(
            run_id="lease-lost-before-recovery",
            correlation_id="corr-lease-lost",
            tenant_id="tenant-a",
            user_id="user-a",
            task=task,
        )
        run.durable_registered = True
        owner._durable_ledger = ledger
        owner._settings = replace(
            owner._settings,
            durable_run_ledger_enabled=True,
            durable_run_ledger_required=True,
        )

        async def observed() -> None:
            while ledger.reads == 0:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(observed(), timeout=2.5)
        assert not task.cancelling()
        assert not task.done()
        assert store.records[run.run_id]["cancel_requested"] is False
        assert ledger.acceptance_attempts == 0
    finally:
        if run is not None and run.heartbeat_task is not None:
            run.heartbeat_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await run.heartbeat_task
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_owner_recovers_cancellation_for_canonical_legacy_tenant() -> None:
    """PostgreSQL canonical UUIDs must match a legacy live tenant scope."""

    from dataclasses import replace

    store = SharedFakeRunStore()
    owner = MedusaRunManager(
        settings=_settings("worker-a"),
        distributed_store=store,
    )
    task = asyncio.create_task(asyncio.sleep(60))
    run = None
    try:
        run = await owner.register(
            run_id="legacy-tenant-cancellation",
            correlation_id="corr-legacy-tenant",
            tenant_id="default",
            user_id="user-a",
            task=task,
        )
        ledger = _RecoveryLedger(tenant_id="default")
        run.durable_registered = True
        owner._durable_ledger = ledger
        owner._settings = replace(
            owner._settings,
            durable_run_ledger_enabled=True,
            durable_run_ledger_required=True,
        )
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=3.5)
        assert store.records[run.run_id]["cancel_requested"] is True
        assert ledger.acceptance_attempts == 1
    finally:
        if run is not None and run.heartbeat_task is not None:
            run.heartbeat_task.cancel()
            try:
                await run.heartbeat_task
            except asyncio.CancelledError:
                pass
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
async def test_slow_postgres_recovery_read_cannot_block_lease_heartbeat() -> None:
    """A stalled durable lookup times out so Redis ownership keeps renewing."""

    from dataclasses import replace

    store = SharedFakeRunStore()
    owner = MedusaRunManager(
        settings=_settings("worker-a"),
        distributed_store=store,
    )
    ledger = _RecoveryLedger(slow_read=True)
    renewed = asyncio.Event()
    calls = 0
    original_heartbeat = store.heartbeat

    async def counting_heartbeat(*, run_id: str, worker_id: str) -> bool:
        nonlocal calls
        result = await original_heartbeat(run_id=run_id, worker_id=worker_id)
        calls += 1
        if calls >= 2:
            renewed.set()
        return result

    store.heartbeat = counting_heartbeat
    task = asyncio.create_task(asyncio.sleep(60))
    run = None
    try:
        run = await owner.register(
            run_id="postgres-stall-recovery",
            correlation_id="corr-postgres-stall",
            tenant_id="tenant-a",
            user_id="user-a",
            task=task,
        )
        run.durable_registered = True
        owner._durable_ledger = ledger
        owner._settings = replace(
            owner._settings,
            durable_run_ledger_enabled=True,
            durable_run_ledger_required=True,
        )
        await asyncio.wait_for(renewed.wait(), timeout=4.5)
        assert ledger.reads >= 1
        assert not task.done()
        assert not task.cancelling()
        assert store.records[run.run_id]["status"] == "running"
        assert store.records[run.run_id]["cancel_requested"] is False
        assert ledger.acceptance_attempts == 0
    finally:
        if run is not None and run.heartbeat_task is not None:
            run.heartbeat_task.cancel()
            try:
                await run.heartbeat_task
            except asyncio.CancelledError:
                pass
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_unverified_retirement_stops_heartbeat_and_retires_shared_claim():
    shared = SharedFakeRunStore()
    owner = MedusaRunManager(settings=_settings("owner"), distributed_store=shared)
    observer = MedusaRunManager(
        settings=_settings("observer"), distributed_store=shared
    )
    task = asyncio.create_task(asyncio.sleep(0))
    scope = dict(run_id="unresolved", tenant_id="tenant-a")
    run = await owner.register(
        **scope, correlation_id="corr", user_id="owner", task=task
    )
    await task
    heartbeat = run.heartbeat_task
    assert heartbeat is not None
    await owner.mark_retirement_unverified("unresolved")
    assert heartbeat.done()
    assert run.heartbeat_task is None
    observed = await observer.get(**scope)
    assert observed["status"] == "orphaned"
    assert observed["error_type"] == "NativeRetirementUnverified"
    assert observed["cancellable"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [-2, -1, 0, 1, 2])
async def test_redis_heartbeat_uses_single_fenced_mutation(result: int) -> None:
    """The advisory read cannot authorize a subsequent metadata write."""
    from types import SimpleNamespace

    from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
        _HEARTBEAT_RUN_SCRIPT,
    )

    class ScriptClient:
        def __init__(self) -> None:
            self.calls: list[tuple[Any, ...]] = []

        async def ping(self) -> bool:
            return True

        async def hgetall(self, key: str) -> dict[str, str]:
            self.calls.append(("read", key))
            return {
                "run_id": "fenced",
                "tenant_id": "tenant-a",
                "owner_worker_id": "worker-a",
                "status": "running",
            }

        async def eval(self, *args: Any) -> int:
            self.calls.append(args)
            return result

    client = ScriptClient()
    settings = _settings("worker-a")
    store = RedisDistributedRunStore(
        settings=settings,
        redis_manager=SimpleNamespace(client=client, is_degraded=lambda: False),
    )
    errors = {
        -2: DistributedRunNotFound,
        -1: DistributedRunOwnershipLost,
        2: DistributedRunStoreUnavailable,
    }
    if result in errors:
        with pytest.raises(errors[result]):
            await store.heartbeat(run_id="fenced", worker_id="worker-a")
    else:
        assert await store.heartbeat(run_id="fenced", worker_id="worker-a") is (
            result == 1
        )
    assert len(client.calls) == 2
    read, mutation = client.calls
    assert read == ("read", store._run_key("fenced"))
    assert mutation[:10] == (
        _HEARTBEAT_RUN_SCRIPT,
        3,
        store._claim_key("fenced"),
        store._run_key("fenced"),
        store._tenant_index("tenant-a"),
        "worker-a",
        "tenant-a",
        "fenced",
        str(settings.run_lease_ttl_seconds),
        str(settings.run_terminal_retention_seconds),
    )
    assert datetime.fromisoformat(mutation[11]) - datetime.fromisoformat(
        mutation[10]
    ) == timedelta(seconds=settings.run_lease_ttl_seconds)
    # Every identity and active-state check precedes the first mutation.
    first_write = _HEARTBEAT_RUN_SCRIPT.index("redis.call('EXPIRE'")
    for guard in (
        "'GET', KEYS[1]",
        "'EXISTS', KEYS[2]",
        "'owner_worker_id'",
        "'tenant_id'",
        "'run_id'",
        "status ~= 'running' and status ~= 'cancelling'",
    ):
        assert _HEARTBEAT_RUN_SCRIPT.index(guard) < first_write
