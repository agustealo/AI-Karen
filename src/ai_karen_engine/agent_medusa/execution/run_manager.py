"""Canonical process-wide execution registry for Agent Medusa runs.

The manager owns observable run state and cancellation for actual coordinator
asyncio tasks. It does not own provider/model routing, prompt assembly, memory,
plugins, or policy. Cancellation is scoped to a concrete request/run and is
therefore enforceable, unlike synthetic per-agent start/stop controls.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ExecutionRunStatus(str, Enum):
    """Canonical lifecycle states for one Medusa execution run."""

    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ExecutionRun:
    """Mutable runtime record for one coordinator request."""

    run_id: str
    correlation_id: str
    tenant_id: str
    user_id: str
    task: asyncio.Task[Any]
    status: ExecutionRunStatus = ExecutionRunStatus.RUNNING
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    error_type: str | None = None

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
    """Raised when a terminal or already-cancelling run is cancelled."""


class MedusaRunManager:
    """Process-wide owner of active Medusa execution tasks and run state."""

    def __init__(self, *, terminal_retention: int = 256) -> None:
        self._runs: dict[str, ExecutionRun] = {}
        self._terminal_order: list[str] = []
        self._terminal_retention = max(1, terminal_retention)
        self._lock = asyncio.Lock()

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
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            run.status = status
            run.completed_at = datetime.now(timezone.utc)
            run.error_type = error_type
            if run_id not in self._terminal_order:
                self._terminal_order.append(run_id)
            self._prune_locked()

    async def cancel(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise RunNotFoundError(run_id)
            if run.tenant_id != tenant_id:
                raise RunTenantMismatchError(run_id)
            if run.status is not ExecutionRunStatus.RUNNING:
                raise RunNotCancellableError(
                    f"Run {run_id} is {run.status.value}, not cancellable"
                )
            run.status = ExecutionRunStatus.CANCELLING
            task = run.task

        task.cancel()
        return await self.get(run_id=run_id, tenant_id=tenant_id)

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise RunNotFoundError(run_id)
            if run.tenant_id != tenant_id:
                raise RunTenantMismatchError(run_id)
            return run.snapshot()

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool = True,
    ) -> list[dict[str, Any]]:
        async with self._lock:
            runs = [
                run.snapshot()
                for run in self._runs.values()
                if run.tenant_id == tenant_id
                and (
                    include_terminal
                    or run.status
                    in {ExecutionRunStatus.RUNNING, ExecutionRunStatus.CANCELLING}
                )
            ]
        return sorted(runs, key=lambda item: item["started_at"], reverse=True)

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
