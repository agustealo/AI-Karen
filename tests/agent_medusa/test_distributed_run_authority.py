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
from ai_karen_engine.agent_medusa.execution.run_manager import (
    ExecutionRunStatus,
    MedusaRunManager,
    RunNotCancellableError,
    RunTenantMismatchError,
)
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
        tenant_id: str,
        worker_id: str,
        status: str,
        completed_at: datetime,
        error_type: str | None,
        outcome_status: str | None = None,
        durable_arbitrated: bool = False,
    ) -> str:
        record = self.records.get(run_id)
        if record is None:
            raise DistributedRunNotFound(run_id)
        if (
            record["worker_id"] != worker_id
            or record["tenant_id"] != tenant_id
            or self._snapshot(record)["status"] not in {"running", "cancelling"}
        ):
            raise DistributedRunOwnershipLost(run_id)
        if record["status"] == "cancelling" and status != "orphaned":
            status, error_type, outcome_status = "cancelled", None, "cancelled"
        record["status"] = status
        record["completed_at"] = completed_at.isoformat()
        record["error_type"] = error_type
        record["outcome_status"] = outcome_status
        record["terminal_authority"] = (
            "durable_arbitrated" if durable_arbitrated else "shared_only"
        )
        return status

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
            "owner_worker_id": record["worker_id"],
            "outcome_status": record.get("outcome_status"),
            "terminal_authority": record.get("terminal_authority"),
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [DistributedRunOwnershipLost, DistributedRunNotFound]
)
@pytest.mark.parametrize("already_cancelling", [False, True])
async def test_observed_lease_loss_fences_local_terminal_results(
    failure: type[Exception], already_cancelling: bool
) -> None:
    """No stale terminal writes or duplicate runtime signal after proven loss."""
    entered_cleanup = asyncio.Event()
    release_cleanup = asyncio.Event()

    class LostStore(SharedFakeRunStore):
        fail_heartbeat = False
        terminal_writes = 0
        outcome_writes = 0

        async def heartbeat(self, *, run_id: str, worker_id: str) -> bool:
            if self.fail_heartbeat:
                raise failure("injected definitive lease loss")
            return await super().heartbeat(run_id=run_id, worker_id=worker_id)

        async def mark_terminal(self, **kwargs: Any) -> str:
            self.terminal_writes += 1
            if kwargs.get("outcome_status") is not None:
                self.outcome_writes += 1
            return await super().mark_terminal(**kwargs)

    class ObservedLedger:
        terminal_writes = 0

        async def mark_terminal(self, **kwargs: Any) -> None:
            self.terminal_writes += 1

    async def workload() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            current = asyncio.current_task()
            assert current is not None
            current.uncancel()
            entered_cleanup.set()
            await release_cleanup.wait()
            raise

    store = LostStore()
    ledger = ObservedLedger()
    manager = MedusaRunManager(settings=_settings("owner"), distributed_store=store)
    task = asyncio.create_task(workload())
    await asyncio.sleep(0)
    scope = dict(run_id="lost-lease", tenant_id="tenant-a")
    run = None
    try:
        run = await manager.register(
            **scope, correlation_id="corr", user_id="owner", task=task
        )
        heartbeat = run.heartbeat_task
        assert heartbeat is not None
        if already_cancelling:
            await manager.cancel(**scope)
            await asyncio.wait_for(entered_cleanup.wait(), timeout=3)
        run.durable_registered = True
        manager._durable_ledger = ledger
        store.fail_heartbeat = True
        await asyncio.wait_for(heartbeat, timeout=4)
        await asyncio.wait_for(entered_cleanup.wait(), timeout=3)
        assert run.shared_ownership_lost
        assert run.heartbeat_task is None
        assert not task.done() and task.cancelling() == 0
        snapshot = await manager.get(**scope)
        assert snapshot["status"] == "orphaned"
        assert snapshot["completed_at"] is None
        assert snapshot["outcome_status"] is None
        assert snapshot["cancellable"] is False
        assert snapshot["distributed_control"]["supported"] is False
        with pytest.raises(RunTenantMismatchError):
            await manager.cancel(run_id=scope["run_id"], tenant_id="foreign")
        with pytest.raises(RunNotCancellableError):
            await manager.cancel(**scope)
        with pytest.raises(RuntimeError, match="already active or unresolved"):
            await manager.register(
                **scope, correlation_id="new", user_id="owner", task=task
            )
        assert await manager.mark_response(
            scope["run_id"], "success"
        ) is ExecutionRunStatus.ORPHANED
        assert await manager.mark_failed(
            scope["run_id"], RuntimeError("late failure")
        ) is ExecutionRunStatus.ORPHANED
        assert await manager.mark_cancelled(
            scope["run_id"]
        ) is ExecutionRunStatus.ORPHANED
        assert run.run_id not in manager._terminal_order
        assert (
            store.terminal_writes
            == store.outcome_writes
            == ledger.terminal_writes
            == 0
        )
        release_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=3)
        assert await manager.mark_cancelled(
            scope["run_id"]
        ) is ExecutionRunStatus.ORPHANED
        assert run.run_id in manager._terminal_order
        assert (
            store.terminal_writes
            == store.outcome_writes
            == ledger.terminal_writes
            == 0
        )
    finally:
        release_cleanup.set()
        if run is not None and run.heartbeat_task is not None:
            run.heartbeat_task.cancel()
            await asyncio.gather(run.heartbeat_task, return_exceptions=True)
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [-3, -2, -1, 0, 1, 2])
async def test_terminal_store_publishes_one_scoped_receipt(result: int) -> None:
    from types import SimpleNamespace

    from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
        _MARK_TERMINAL_SCRIPT,
    )

    class ScriptClient:
        def __init__(self) -> None:
            self.calls: list[tuple[Any, ...]] = []

        async def ping(self) -> bool:
            return True

        async def eval(self, *args: Any) -> int:
            self.calls.append(args)
            return result

    client = ScriptClient()
    settings = _settings("worker-a")
    store = RedisDistributedRunStore(
        settings=settings,
        redis_manager=SimpleNamespace(client=client, is_degraded=lambda: False),
    )
    completed_at = datetime.now(timezone.utc)
    args = dict(
        run_id="terminal-run",
        tenant_id="tenant-a",
        worker_id="worker-a",
        status="completed",
        completed_at=completed_at,
        error_type=None,
        outcome_status="success",
    )
    errors = {
        -3: ValueError,
        -2: DistributedRunNotFound,
        -1: DistributedRunOwnershipLost,
        0: DistributedRunStoreUnavailable,
    }
    if result in errors:
        with pytest.raises(errors[result]):
            await store.mark_terminal(**args)
    else:
        assert await store.mark_terminal(**args) == (
            "cancelled" if result == 2 else "completed"
        )
    assert client.calls == [
        (
            _MARK_TERMINAL_SCRIPT,
            4,
            store._claim_key("terminal-run"),
            store._run_key("terminal-run"),
            store._tenant_index("tenant-a"),
            store._pending_terminal_index("tenant-a"),
            "worker-a",
            "tenant-a",
            "terminal-run",
            "completed",
            store._iso(completed_at),
            "",
            "success",
            str(settings.run_terminal_retention_seconds),
            "shared_only",
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["cancel", "lost", "unavailable"])
async def test_terminal_publication_waits_for_shared_authority(mode: str) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingTerminalStore(SharedFakeRunStore):
        async def mark_terminal(self, **kwargs: Any) -> str:
            entered.set()
            await release.wait()
            if mode == "lost":
                raise DistributedRunOwnershipLost("injected")
            if mode == "unavailable":
                raise DistributedRunStoreUnavailable("injected")
            return await super().mark_terminal(**kwargs)

    store = BlockingTerminalStore()
    manager = MedusaRunManager(settings=_settings("owner"), distributed_store=store)
    task = asyncio.create_task(asyncio.sleep(60))
    finalizer = None
    scope = dict(run_id="terminal-race", tenant_id="tenant-a")
    try:
        run = await manager.register(
            **scope, correlation_id="corr", user_id="owner", task=task
        )
        if mode == "cancel":
            await store.request_cancel(**scope)
        finalizer = asyncio.create_task(manager.mark_response(run.run_id, "success"))
        await asyncio.wait_for(entered.wait(), timeout=2)
        snapshot = await manager.get(**scope)
        assert snapshot["status"] == "running"
        assert snapshot["outcome_status"] is None
        assert not snapshot["cancellable"]
        with pytest.raises(DistributedRunStoreUnavailable):
            await manager.mark_response(run.run_id, "success")
        release.set()
        expected = (
            ExecutionRunStatus.CANCELLED
            if mode == "cancel"
            else ExecutionRunStatus.ORPHANED
        )
        assert await asyncio.wait_for(finalizer, timeout=2) is expected
        snapshot = await manager.get(**scope)
        assert snapshot["status"] == expected.value
        assert snapshot["outcome_status"] == (
            "cancelled" if mode == "cancel" else None
        )
        assert await manager.mark_response(run.run_id, "success") is expected
        if mode != "cancel":
            assert snapshot["completed_at"] is None
            assert store.records[run.run_id]["status"] == "running"
    finally:
        release.set()
        if finalizer is not None:
            await asyncio.gather(finalizer, return_exceptions=True)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [0, 1])
async def test_durable_receipt_retention_acknowledgement_is_exact(result: int) -> None:
    from types import SimpleNamespace

    from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
        _ACK_DURABLE_TERMINAL_SCRIPT,
    )

    class Client:
        calls: list[tuple[Any, ...]] = []

        async def ping(self) -> bool:
            return True

        async def eval(self, *args: Any) -> int:
            self.calls.append(args)
            return result

    client = Client()
    settings = _settings("observer")
    store = RedisDistributedRunStore(
        settings=settings,
        redis_manager=SimpleNamespace(client=client, is_degraded=lambda: False),
    )
    receipt = {
        "run_id": "receipt",
        "tenant_id": "tenant-a",
        "owner_worker_id": "owner",
        "correlation_id": "corr",
        "user_id": "user",
        "status": "completed",
        "completed_at": "2026-11-26T10:00:00+00:00",
        "error_type": None,
        "outcome_status": "success",
    }
    from ai_karen_engine.platform.observability.metrics import get_metrics_collector

    store._now = lambda: datetime(2026, 11, 26, 10, 1, tzinfo=timezone.utc)
    name = "kari_medusa_terminal_retention_acknowledged_age_seconds"

    def snapshot():
        return get_metrics_collector().snapshot()["histograms"].get(name, {}).get("values", {}).get(())

    before = snapshot()
    assert await store.acknowledge_durable_terminal(
        tenant_id="tenant-a", receipt=receipt
    ) is bool(result)
    after = snapshot()
    if result == 1:
        assert after.count == (before.count if before else 0) + 1
        assert after.total == (before.total if before else 0) + 60
    else:
        assert after == before
    assert client.calls == [
        (
            _ACK_DURABLE_TERMINAL_SCRIPT,
            3,
            store._claim_key("receipt"),
            store._run_key("receipt"),
            store._pending_terminal_index("tenant-a"),
            "run_id", "receipt",
            "tenant_id", "tenant-a",
            "owner_worker_id", "owner",
            "correlation_id", "corr",
            "user_id", "user",
            "status", "completed",
            "completed_at", receipt["completed_at"],
            "error_type", "",
            "outcome_status", "success",
            str(settings.run_terminal_retention_seconds),
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "stage", "reason"),
    [
        ("get", "transaction", "shared_run_observation_unavailable"),
        ("list", "index", "shared_run_index_unavailable"),
        ("list", "transaction", "shared_run_observation_unavailable"),
        ("list", "cleanup", "shared_run_index_cleanup_unavailable"),
        ("cancel", "read", "shared_cancel_read_unavailable"),
        ("cancel", "signal", "shared_cancel_signal_unconfirmed"),
        ("cancel", "transaction", "shared_run_observation_unavailable"),
    ],
)
async def test_redis_disconnect_after_health_check_is_typed(
    operation: str, stage: str, reason: str
) -> None:
    from types import SimpleNamespace

    from redis.exceptions import ConnectionError as RedisConnectionError

    failure = RedisConnectionError("private connection diagnostic")

    class Client:
        async def ping(self) -> bool:
            return True

        def pipeline(self, *, transaction: bool):
            assert transaction

            class Pipeline:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args: Any) -> None:
                    pass

                def hgetall(self, _key: str) -> None:
                    pass

                def get(self, _key: str) -> None:
                    pass

                async def execute(self):
                    if stage == "transaction":
                        raise failure
                    return {}, None

            return Pipeline()

        async def smembers(self, _key: str):
            if stage == "index":
                raise failure
            return {"run-a"}

        async def srem(self, *_args: Any):
            assert stage == "cleanup"
            raise failure

        async def eval(self, *_args: Any) -> int:
            if stage == "signal":
                raise failure
            return 1

        async def hgetall(self, _key: str):
            if stage == "read":
                raise failure
            return {"run_id": "run-a", "tenant_id": "tenant-a"}

    store = RedisDistributedRunStore(
        settings=_settings("owner"),
        redis_manager=SimpleNamespace(client=Client(), is_degraded=lambda: False),
    )
    with pytest.raises(DistributedRunStoreUnavailable, match=reason) as exc:
        if operation == "get":
            await store.get(run_id="run-a", tenant_id="tenant-a")
        elif operation == "list":
            await store.list_runs(tenant_id="tenant-a", include_terminal=True)
        else:
            await store.request_cancel(run_id="run-a", tenant_id="tenant-a")
    assert exc.value.__cause__ is failure
    assert "private connection diagnostic" not in str(exc.value)


@pytest.mark.asyncio
async def test_owner_read_preserves_uncertain_terminal_during_redis_disconnect() -> None:
    from types import SimpleNamespace

    from redis.exceptions import ConnectionError as RedisConnectionError

    from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
        _MARK_TERMINAL_SCRIPT,
        _REGISTER_RUN_SCRIPT,
    )

    class Pipeline:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: Any) -> None:
            pass

        def hgetall(self, _key: str) -> None:
            pass

        def get(self, _key: str) -> None:
            pass

        async def execute(self):
            raise RedisConnectionError("injected post-ping disconnect")

    class Client:
        terminal_attempts = 0
        observations = 0

        async def ping(self) -> bool:
            return True

        async def eval(self, script: str, *_args: Any) -> int:
            if script == _REGISTER_RUN_SCRIPT:
                return 1
            assert script == _MARK_TERMINAL_SCRIPT
            self.terminal_attempts += 1
            raise RedisConnectionError("injected lost terminal acknowledgement")

        def pipeline(self, *, transaction: bool):
            assert transaction
            self.observations += 1
            return Pipeline()

    client = Client()
    settings = _settings("owner")
    store = RedisDistributedRunStore(
        settings=settings,
        redis_manager=SimpleNamespace(client=client, is_degraded=lambda: False),
    )
    manager = MedusaRunManager(settings=settings, distributed_store=store)
    scope = {"run_id": "uncertain-outage", "tenant_id": "tenant-a"}
    task = asyncio.create_task(asyncio.sleep(0))
    run = None
    try:
        run = await manager.register(
            **scope, correlation_id="corr", user_id="owner", task=task
        )
        await task
        assert run.shared_registered
        assert (
            await manager.mark_response(run.run_id, "success")
            is ExecutionRunStatus.ORPHANED
        )
        assert run.terminal_unconfirmed
        for _ in range(2):
            snapshot = await manager.get(**scope)
            assert snapshot["status"] == "orphaned"
            assert snapshot["error_type"] == "TerminalCommitUnconfirmed"
            assert snapshot["completed_at"] is None
            assert snapshot["outcome_status"] is None
            assert not snapshot["cancellable"]
        assert client.observations == 2
        assert (
            await manager.mark_response(run.run_id, "success")
            is ExecutionRunStatus.ORPHANED
        )
        assert client.terminal_attempts == 1
        with pytest.raises(RunTenantMismatchError):
            await manager.get(run_id=run.run_id, tenant_id="foreign")
        assert client.observations == 2
    finally:
        if run is not None and run.heartbeat_task is not None:
            run.heartbeat_task.cancel()
            await asyncio.gather(run.heartbeat_task, return_exceptions=True)
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "limit", "used", "excluded", "reason"), [
    ("observed", 100, 80, 10, None),
    ("observed", 100, 80, 9, "redis_capacity_reserve_exhausted"),
    ("observed", 100, 110, 5, "redis_capacity_reserve_exhausted"),
    ("observed", 0, 80, 0, "redis_capacity_unverified"),
    ("observed", 100, 80, 81, "redis_capacity_unverified"),
    ("observed", 100, None, 0, "redis_capacity_unverified"),
    ("partial", 100, 10, 0, "redis_capacity_unverified"),
    ("unavailable", 100, 10, 0, "redis_capacity_unverified"),
])
async def test_redis_registration_reserve(status, limit, used, excluded, reason):
    from dataclasses import replace
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
        DistributedRunAdmissionRejected,
    )
    from ai_karen_engine.platform.memory.redis.redis_connection_manager import (
        RedisDurabilityObservation,
    )

    client = SimpleNamespace(ping=AsyncMock(return_value=True), eval=AsyncMock(return_value=1))
    manager = SimpleNamespace(
        client=client,
        is_degraded=lambda: False,
        observe_durability=AsyncMock(return_value=RedisDurabilityObservation(
            status=status, maxmemory_bytes=limit, used_memory_bytes=used,
            mem_not_counted_for_evict_bytes=excluded,
        )),
    )
    store = RedisDistributedRunStore(
        settings=replace(_settings("owner"), run_redis_admission_reserve_bytes=30),
        redis_manager=manager,
    )
    args = dict(run_id="reserve", correlation_id="corr", tenant_id="tenant-a",
                user_id="user", worker_id="owner", started_at=datetime.now(timezone.utc))
    if reason is None:
        await store.register(**args)
        client.eval.assert_awaited_once()
    else:
        with pytest.raises(DistributedRunAdmissionRejected, match=reason):
            await store.register(**args)
        client.eval.assert_not_awaited()
    manager.observe_durability.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unavailable", "replacement", "degraded", "oom", "cancel"])
async def test_redis_guard_never_writes_using_invalid_capacity_evidence(failure):
    from dataclasses import replace
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from redis.exceptions import OutOfMemoryError

    from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
        DistributedRunAdmissionRejected,
    )
    from ai_karen_engine.platform.memory.redis.redis_connection_manager import (
        RedisDurabilityObservation,
    )

    client = SimpleNamespace(ping=AsyncMock(return_value=failure != "unavailable"),
                             eval=AsyncMock(return_value=1))
    manager = SimpleNamespace(client=client, degraded=False)
    manager.is_degraded = lambda: manager.degraded

    async def observe():
        if failure == "replacement":
            manager.client = object()
        if failure == "degraded":
            manager.degraded = True
        if failure == "cancel":
            raise asyncio.CancelledError
        return RedisDurabilityObservation(
            status="observed", maxmemory_bytes=100, used_memory_bytes=10,
            mem_not_counted_for_evict_bytes=0,
        )

    manager.observe_durability = observe
    if failure == "oom":
        client.eval.side_effect = OutOfMemoryError("private server detail")
    store = RedisDistributedRunStore(
        settings=replace(_settings("owner"), run_redis_admission_reserve_bytes=30),
        redis_manager=manager,
    )
    args = dict(run_id="reserve", correlation_id="corr", tenant_id="tenant-a",
                user_id="user", worker_id="owner", started_at=datetime.now(timezone.utc))
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await store.register(**args)
    else:
        reason = "redis_registration_oom" if failure == "oom" else "redis_capacity_unverified"
        with pytest.raises(DistributedRunAdmissionRejected, match=reason) as exc:
            await store.register(**args)
        assert "private server detail" not in str(exc.value)
    if failure == "oom":
        client.eval.assert_awaited_once()
    else:
        client.eval.assert_not_awaited()



@pytest.mark.asyncio
@pytest.mark.parametrize("reserve", [0, 30])
@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (0, "redis_registration_conflict"),
        (None, "redis_registration_unconfirmed"),
        (True, "redis_registration_unconfirmed"),
        (2, "redis_registration_unconfirmed"),
        ("1", "redis_registration_unconfirmed"),
        ("timeout", "redis_registration_unconfirmed"),
        ("connection", "redis_registration_unconfirmed"),
        ("script", "redis_registration_unconfirmed"),
        (1, None),
    ],
)
async def test_registration_requires_exact_shared_acknowledgement(reserve, reply, reason):
    from dataclasses import replace
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from redis.exceptions import ConnectionError, ResponseError, TimeoutError

    from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
        DistributedRunAdmissionRejected,
    )
    from ai_karen_engine.platform.memory.redis.redis_connection_manager import (
        RedisDurabilityObservation,
    )

    client = SimpleNamespace(
        ping=AsyncMock(return_value=True), eval=AsyncMock(return_value=reply)
    )
    errors = {
        "timeout": TimeoutError,
        "connection": ConnectionError,
        "script": ResponseError,
    }
    if reply in errors:
        client.eval.side_effect = errors[reply]("private transport detail")
    manager = SimpleNamespace(
        client=client,
        is_degraded=lambda: False,
        observe_durability=AsyncMock(
            return_value=RedisDurabilityObservation(
                status="observed",
                maxmemory_bytes=100,
                used_memory_bytes=10,
                mem_not_counted_for_evict_bytes=0,
            )
        ),
    )
    store = RedisDistributedRunStore(
        settings=replace(_settings("owner"), run_redis_admission_reserve_bytes=reserve),
        redis_manager=manager,
    )
    args = dict(
        run_id="reserve",
        correlation_id="corr",
        tenant_id="tenant-a",
        user_id="user",
        worker_id="owner",
        started_at=datetime.now(timezone.utc),
    )
    if reason is None:
        await store.register(**args)
    else:
        with pytest.raises(DistributedRunAdmissionRejected, match=reason) as exc:
            await store.register(**args)
        assert "private transport detail" not in str(exc.value)
    client.eval.assert_awaited_once()


def test_redis_admission_reserve_configuration_is_validated():
    from dataclasses import replace
    from ai_karen_engine.config.agent_medusa import AgentMedusaConfigError

    for invalid in (-1, True, 1.5):
        with pytest.raises(AgentMedusaConfigError, match="nonnegative integer"):
            replace(_settings("owner"), run_redis_admission_reserve_bytes=invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ([0, []], []),
        ([3, ["first", "second"]], ["first", "second"]),
        ([3, ["first"]], None),
        ([True, ["first"]], None),
        ([-1, []], None),
        ([1, [None]], None),
        (["2", ["first", "second"]], None),
    ],
)
async def test_pending_terminal_discovery_observes_index_members(result, expected):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from ai_karen_engine.platform.observability.metrics import get_metrics_collector

    name = "kari_medusa_terminal_retention_index_entries_observed"

    def snapshot():
        return get_metrics_collector().snapshot()["histograms"].get(name, {}).get("values", {}).get(())

    before = snapshot()
    client = SimpleNamespace(
        ping=AsyncMock(return_value=True), eval=AsyncMock(return_value=result),
    )
    store = RedisDistributedRunStore(
        settings=_settings("observer"),
        redis_manager=SimpleNamespace(client=client, is_degraded=lambda: False),
    )
    if expected is None:
        with pytest.raises(DistributedRunStoreUnavailable, match="invalid_terminal_discovery_result"):
            await store.pending_terminal_ids(tenant_id="tenant-private", limit=2)
        assert snapshot() == before
    else:
        assert await store.pending_terminal_ids(tenant_id="tenant-private", limit=2) == expected
        after = snapshot()
        assert after.count == (before.count if before else 0) + 1
        assert after.total == (before.total if before else 0) + result[0]
    client.eval.assert_awaited_once()


@pytest.mark.parametrize("value", [-1, float("inf"), float("nan"), True, "raw"])
def test_retention_observation_rejects_invalid_age(value, monkeypatch):
    from ai_karen_engine.agent_medusa.telemetry import metrics
    from ai_karen_engine.platform.observability.metrics import MetricsCollector

    collector = MetricsCollector()
    monkeypatch.setattr(metrics, "get_metrics_collector", lambda: collector)
    metrics.record_retention_observation("acknowledged_age", value)
    assert collector.snapshot()["histograms"] == {}
