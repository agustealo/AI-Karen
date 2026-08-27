from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
    DistributedRunNotCancellable,
    DistributedRunNotFound,
    DistributedRunTenantMismatch,
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
