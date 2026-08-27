"""Canonical execution authority for Agent Medusa runs.

Concrete asyncio tasks remain owned by the worker process that executes them.
Shared Redis coordination adds cluster-wide observation, leases, orphan
detection, and remote cancellation requests without pretending another worker
can directly cancel a task it does not own.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ai_karen_engine.config.agent_medusa import (
    AgentMedusaRuntimeSettings,
    get_agent_medusa_runtime_settings,
)
from ai_karen_engine.core.logging import get_logger

from .distributed_run_store import (
    DistributedRunNotCancellable,
    DistributedRunNotFound,
    DistributedRunStore,
    DistributedRunStoreUnavailable,
    DistributedRunTenantMismatch,
    RedisDistributedRunStore,
)

logger = get_logger(__name__)


class ExecutionRunStatus(str, Enum):
    """Canonical lifecycle states for one local Medusa execution run."""

    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ExecutionRun:
    """Mutable worker-local record for one coordinator request."""

    run_id: str
    correlation_id: str
    tenant_id: str
    user_id: str
    task: asyncio.Task[Any]
    status: ExecutionRunStatus = ExecutionRunStatus.RUNNING
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    error_type: str | None = None
    shared_registered: bool = False
    heartbeat_task: asyncio.Task[None] | None = field(default=None, repr=False)

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "correlation_id": self.correlation_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_type": self.error_type,
            "cancellable": self.status is ExecutionRunStatus.RUNNING,
        }


class RunNotFoundError(LookupError):
    """Raised when a requested execution run is unknown."""


class RunTenantMismatchError(PermissionError):
    """Raised when an operator crosses tenant scope."""


class RunNotCancellableError(RuntimeError):
    """Raised when a terminal, orphaned, or cancelling run is cancelled."""


class MedusaRunManager:
    """Own local tasks while coordinating run truth across runtime workers."""

    def __init__(
        self,
        *,
        terminal_retention: int = 256,
        settings: AgentMedusaRuntimeSettings | None = None,
        distributed_store: DistributedRunStore | None = None,
    ) -> None:
        self._runs: dict[str, ExecutionRun] = {}
        self._terminal_order: list[str] = []
        self._terminal_retention = max(1, terminal_retention)
        self._lock = asyncio.Lock()
        self._settings = settings or get_agent_medusa_runtime_settings()
        self._distributed_store = distributed_store or RedisDistributedRunStore(
            settings=self._settings
        )

    async def register(
        self,
        *,
        run_id: str,
        correlation_id: str,
        tenant_id: str,
        user_id: str,
        task: asyncio.Task[Any],
    ) -> ExecutionRun:
        async with self._lock:
            existing = self._runs.get(run_id)
            if existing is not None and existing.status in {
                ExecutionRunStatus.RUNNING,
                ExecutionRunStatus.CANCELLING,
            }:
                raise RuntimeError(f"Medusa run already active: {run_id}")
            run = ExecutionRun(
                run_id=run_id,
                correlation_id=correlation_id,
                tenant_id=tenant_id,
                user_id=user_id,
                task=task,
            )
            self._runs[run_id] = run

        if await self._distributed_available():
            try:
                await self._distributed_store.register(
                    run_id=run_id,
                    correlation_id=correlation_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    worker_id=self._settings.worker_id,
                    started_at=run.started_at,
                )
            except DistributedRunStoreUnavailable:
                logger.warning(
                    "Medusa distributed coordination unavailable during registration",
                    extra={"run_id": run_id, "correlation_id": correlation_id},
                )
            except Exception:
                async with self._lock:
                    if self._runs.get(run_id) is run:
                        self._runs.pop(run_id, None)
                raise
            else:
                async with self._lock:
                    run.shared_registered = True
                    run.heartbeat_task = asyncio.create_task(
                        self._heartbeat_loop(run),
                        name=f"medusa-run-heartbeat:{run_id}",
                    )

        return run

    async def mark_completed(self, run_id: str) -> None:
        await self._mark_terminal(run_id, ExecutionRunStatus.COMPLETED)

    async def mark_failed(self, run_id: str, exc: BaseException) -> None:
        await self._mark_terminal(
            run_id,
            ExecutionRunStatus.FAILED,
            error_type=type(exc).__name__,
        )

    async def mark_cancelled(self, run_id: str) -> None:
        await self._mark_terminal(run_id, ExecutionRunStatus.CANCELLED)

    async def _mark_terminal(
        self,
        run_id: str,
        status: ExecutionRunStatus,
        *,
        error_type: str | None = None,
    ) -> None:
        heartbeat_task: asyncio.Task[None] | None = None
        shared_registered = False
        completed_at = datetime.now(timezone.utc)
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            run.status = status
            run.completed_at = completed_at
            run.error_type = error_type
            heartbeat_task = run.heartbeat_task
            run.heartbeat_task = None
            shared_registered = run.shared_registered
            if run_id not in self._terminal_order:
                self._terminal_order.append(run_id)
            self._prune_locked()

        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        if shared_registered:
            try:
                await self._distributed_store.mark_terminal(
                    run_id=run_id,
                    worker_id=self._settings.worker_id,
                    status=status.value,
                    completed_at=completed_at,
                    error_type=error_type,
                )
            except DistributedRunStoreUnavailable:
                logger.warning(
                    "Medusa terminal state could not be written to shared coordination",
                    extra={"run_id": run_id, "status": status.value},
                )

    async def cancel(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        local_task: asyncio.Task[Any] | None = None
        local_shared = False
        async with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                if run.tenant_id != tenant_id:
                    raise RunTenantMismatchError(run_id)
                if run.status is not ExecutionRunStatus.RUNNING:
                    raise RunNotCancellableError(
                        f"Run {run_id} is {run.status.value}, not cancellable"
                    )
                run.status = ExecutionRunStatus.CANCELLING
                local_task = run.task
                local_shared = run.shared_registered

        if local_task is not None:
            if local_shared:
                try:
                    await self._distributed_store.request_cancel(
                        run_id=run_id,
                        tenant_id=tenant_id,
                    )
                except DistributedRunStoreUnavailable:
                    logger.warning(
                        "Shared cancel state unavailable; cancelling local task directly",
                        extra={"run_id": run_id},
                    )
                except DistributedRunNotCancellable:
                    pass
            local_task.cancel()
            return await self.get(run_id=run_id, tenant_id=tenant_id)

        if not await self._distributed_available():
            raise RunNotFoundError(run_id)
        try:
            return await self._distributed_store.request_cancel(
                run_id=run_id,
                tenant_id=tenant_id,
            )
        except DistributedRunNotFound as exc:
            raise RunNotFoundError(run_id) from exc
        except DistributedRunTenantMismatch as exc:
            raise RunTenantMismatchError(run_id) from exc
        except DistributedRunNotCancellable as exc:
            raise RunNotCancellableError(str(exc)) from exc
        except DistributedRunStoreUnavailable as exc:
            raise RunNotFoundError(run_id) from exc

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                if run.tenant_id != tenant_id:
                    raise RunTenantMismatchError(run_id)
                snapshot = run.snapshot()
                shared_registered = run.shared_registered
            else:
                snapshot = None
                shared_registered = False

        if snapshot is not None:
            snapshot["distributed_control"] = await self._distributed_capability(
                shared_registered=shared_registered
            )
            return snapshot

        if not await self._distributed_available():
            raise RunNotFoundError(run_id)
        try:
            return await self._distributed_store.get(run_id=run_id, tenant_id=tenant_id)
        except DistributedRunNotFound as exc:
            raise RunNotFoundError(run_id) from exc
        except DistributedRunTenantMismatch as exc:
            raise RunTenantMismatchError(run_id) from exc
        except DistributedRunStoreUnavailable as exc:
            raise RunNotFoundError(run_id) from exc

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool = True,
    ) -> list[dict[str, Any]]:
        async with self._lock:
            local_pairs = [
                (run.snapshot(), run.shared_registered)
                for run in self._runs.values()
                if run.tenant_id == tenant_id
                and (
                    include_terminal
                    or run.status
                    in {ExecutionRunStatus.RUNNING, ExecutionRunStatus.CANCELLING}
                )
            ]

        merged: dict[str, dict[str, Any]] = {}
        for snapshot, shared_registered in local_pairs:
            snapshot["distributed_control"] = await self._distributed_capability(
                shared_registered=shared_registered
            )
            merged[snapshot["run_id"]] = snapshot

        if await self._distributed_available():
            try:
                shared = await self._distributed_store.list_runs(
                    tenant_id=tenant_id,
                    include_terminal=include_terminal,
                )
            except DistributedRunStoreUnavailable:
                shared = []
            for snapshot in shared:
                run_id = snapshot["run_id"]
                if run_id not in merged or run_id not in self._runs:
                    merged[run_id] = snapshot

        return sorted(
            merged.values(),
            key=lambda item: item["started_at"] or "",
            reverse=True,
        )

    async def _heartbeat_loop(self, run: ExecutionRun) -> None:
        try:
            while True:
                await asyncio.sleep(self._settings.run_heartbeat_interval_seconds)
                try:
                    cancel_requested = await self._distributed_store.heartbeat(
                        run_id=run.run_id,
                        worker_id=self._settings.worker_id,
                    )
                except DistributedRunStoreUnavailable:
                    logger.warning(
                        "Medusa shared run heartbeat unavailable",
                        extra={"run_id": run.run_id},
                    )
                    continue
                if cancel_requested:
                    async with self._lock:
                        current = self._runs.get(run.run_id)
                        if current is not run:
                            return
                        if current.status is ExecutionRunStatus.RUNNING:
                            current.status = ExecutionRunStatus.CANCELLING
                        task = current.task
                    task.cancel()
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "Medusa shared run heartbeat failed",
                extra={
                    "run_id": run.run_id,
                    "error_type": type(exc).__name__,
                },
            )

    async def _distributed_available(self) -> bool:
        if not self._settings.distributed_run_control_enabled:
            return False
        try:
            return await self._distributed_store.available()
        except Exception:
            return False

    async def _distributed_capability(
        self,
        *,
        shared_registered: bool,
    ) -> dict[str, Any]:
        if not self._settings.distributed_run_control_enabled:
            return {
                "supported": False,
                "reason_code": "distributed_run_control_disabled",
            }
        if not shared_registered:
            return {
                "supported": False,
                "reason_code": "run_not_registered_in_shared_coordination",
            }
        if not await self._distributed_available():
            return {
                "supported": False,
                "reason_code": "shared_redis_unavailable",
            }
        return {"supported": True, "lease_alive": True}

    def _prune_locked(self) -> None:
        excess = len(self._terminal_order) - self._terminal_retention
        if excess <= 0:
            return
        for run_id in self._terminal_order[:excess]:
            run = self._runs.get(run_id)
            if run is not None and run.status not in {
                ExecutionRunStatus.RUNNING,
                ExecutionRunStatus.CANCELLING,
            }:
                self._runs.pop(run_id, None)
        del self._terminal_order[:excess]


_RUN_MANAGER: MedusaRunManager | None = None


def get_medusa_run_manager() -> MedusaRunManager:
    """Return the process-wide execution registry."""

    global _RUN_MANAGER
    if _RUN_MANAGER is None:
        _RUN_MANAGER = MedusaRunManager()
    return _RUN_MANAGER


__all__ = [
    "ExecutionRunStatus",
    "MedusaRunManager",
    "RunNotCancellableError",
    "RunNotFoundError",
    "RunTenantMismatchError",
    "get_medusa_run_manager",
]
