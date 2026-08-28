"""Canonical execution authority for Agent Medusa runs.

Concrete asyncio tasks remain owned by the worker process that executes them.
Redis owns transient cluster coordination. PostgreSQL owns durable execution
history. Neither persistence layer is allowed to pretend it owns a concrete
asyncio task.
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
from .run_ledger import (
    MedusaRunLedger,
    MedusaRunLedgerConflict,
    MedusaRunLedgerNotFound,
    PostgresMedusaRunLedger,
)

logger = get_logger(__name__)


class ExecutionRunStatus(str, Enum):
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ExecutionRun:
    run_id: str
    correlation_id: str
    tenant_id: str
    user_id: str
    task: asyncio.Task[Any]
    request_id: str | None = None
    policy_decision_id: str | None = None
    status: ExecutionRunStatus = ExecutionRunStatus.RUNNING
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    error_type: str | None = None
    shared_registered: bool = False
    durable_registered: bool = False
    heartbeat_task: asyncio.Task[None] | None = field(default=None, repr=False)

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "correlation_id": self.correlation_id,
            "request_id": self.request_id,
            "policy_decision_id": self.policy_decision_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_type": self.error_type,
            "cancellable": self.status is ExecutionRunStatus.RUNNING,
            "durable_history": {
                "supported": self.durable_registered,
                "source": "postgresql" if self.durable_registered else None,
                "reason_code": (
                    None
                    if self.durable_registered
                    else "run_not_registered_in_durable_history"
                ),
            },
        }


class RunNotFoundError(LookupError):
    pass


class RunTenantMismatchError(PermissionError):
    pass


class RunNotCancellableError(RuntimeError):
    pass


class MedusaRunManager:
    """Own concrete local tasks while combining Redis and PostgreSQL truth."""

    _DURABLE_ACTIVE = {"created", "running", "cancellation_requested"}

    def __init__(
        self,
        *,
        terminal_retention: int = 256,
        settings: AgentMedusaRuntimeSettings | None = None,
        distributed_store: DistributedRunStore | None = None,
        durable_ledger: MedusaRunLedger | None = None,
    ) -> None:
        self._runs: dict[str, ExecutionRun] = {}
        self._terminal_order: list[str] = []
        self._terminal_retention = max(1, terminal_retention)
        self._lock = asyncio.Lock()
        self._settings = settings or get_agent_medusa_runtime_settings()
        self._distributed_store = distributed_store or RedisDistributedRunStore(
            settings=self._settings
        )
        self._durable_ledger = durable_ledger or PostgresMedusaRunLedger()

    async def register(
        self,
        *,
        run_id: str,
        correlation_id: str,
        tenant_id: str,
        user_id: str,
        task: asyncio.Task[Any],
        request_id: str | None = None,
        policy_decision_id: str | None = None,
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
                request_id=request_id,
                policy_decision_id=policy_decision_id,
                tenant_id=tenant_id,
                user_id=user_id,
                task=task,
            )
            self._runs[run_id] = run

        await self._register_durable(run)
        await self._register_distributed(run)
        return run

    async def _register_durable(self, run: ExecutionRun) -> None:
        if not self._settings.durable_run_history_enabled:
            return
        try:
            await self._durable_ledger.register_running(
                run_id=run.run_id,
                correlation_id=run.correlation_id,
                request_id=run.request_id,
                policy_decision_id=run.policy_decision_id,
                tenant_id=run.tenant_id,
                user_id=run.user_id,
                worker_id=self._settings.worker_id,
                started_at=run.started_at,
            )
        except MedusaRunLedgerConflict:
            async with self._lock:
                self._runs.pop(run.run_id, None)
            raise
        except Exception as exc:
            logger.error(
                "Medusa durable run registration unavailable",
                extra={
                    "run_id": run.run_id,
                    "correlation_id": run.correlation_id,
                    "tenant_id": run.tenant_id,
                    "error_type": type(exc).__name__,
                },
            )
        else:
            run.durable_registered = True

    async def _register_distributed(self, run: ExecutionRun) -> None:
        if not await self._distributed_available():
            return
        try:
            await self._distributed_store.register(
                run_id=run.run_id,
                correlation_id=run.correlation_id,
                tenant_id=run.tenant_id,
                user_id=run.user_id,
                worker_id=self._settings.worker_id,
                started_at=run.started_at,
            )
        except DistributedRunStoreUnavailable:
            logger.warning(
                "Medusa distributed coordination unavailable during registration",
                extra={"run_id": run.run_id, "correlation_id": run.correlation_id},
            )
        except Exception:
            async with self._lock:
                self._runs.pop(run.run_id, None)
            if run.durable_registered:
                await self._safe_mark_durable_terminal(
                    run,
                    status="failed",
                    error_type="DistributedRegistrationError",
                    reason_code="distributed_registration_failed",
                )
            raise
        else:
            run.shared_registered = True
            run.heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(run),
                name=f"medusa-run-heartbeat:{run.run_id}",
            )

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
            if run_id not in self._terminal_order:
                self._terminal_order.append(run_id)
            self._prune_locked()

        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        if run.shared_registered:
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

        if run.durable_registered:
            await self._safe_mark_durable_terminal(
                run,
                status=status.value,
                completed_at=completed_at,
                error_type=error_type,
            )

    async def cancel(
        self,
        *,
        run_id: str,
        tenant_id: str,
        audit_event_id: str | None = None,
    ) -> dict[str, Any]:
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

        if run is not None:
            if run.shared_registered:
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
            await self._safe_request_durable_cancel(
                run_id=run_id,
                tenant_id=tenant_id,
                audit_event_id=audit_event_id,
            )
            run.task.cancel()
            return await self.get(run_id=run_id, tenant_id=tenant_id)

        if not await self._distributed_available():
            durable = await self._get_durable(run_id=run_id, tenant_id=tenant_id)
            if durable is not None:
                raise RunNotCancellableError(
                    f"Run {run_id} has durable state {durable['status']} "
                    "but live ownership is unavailable"
                )
            raise RunNotFoundError(run_id)

        try:
            shared = await self._distributed_store.request_cancel(
                run_id=run_id,
                tenant_id=tenant_id,
            )
        except DistributedRunNotFound as exc:
            await self._reconcile_missing(run_id=run_id, tenant_id=tenant_id)
            raise RunNotFoundError(run_id) from exc
        except DistributedRunTenantMismatch as exc:
            raise RunTenantMismatchError(run_id) from exc
        except DistributedRunNotCancellable as exc:
            raise RunNotCancellableError(str(exc)) from exc
        except DistributedRunStoreUnavailable as exc:
            raise RunNotFoundError(run_id) from exc

        await self._safe_request_durable_cancel(
            run_id=run_id,
            tenant_id=tenant_id,
            audit_event_id=audit_event_id,
        )
        shared["durable_history"] = await self._durable_capability(run_id, tenant_id)
        return shared

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        async with self._lock:
            local = self._runs.get(run_id)
            if local is not None and local.tenant_id != tenant_id:
                raise RunTenantMismatchError(run_id)

        if local is not None:
            snapshot = local.snapshot()
            snapshot["distributed_control"] = await self._distributed_capability(
                local.shared_registered
            )
            return snapshot

        if await self._distributed_available():
            try:
                shared = await self._distributed_store.get(
                    run_id=run_id,
                    tenant_id=tenant_id,
                )
            except DistributedRunTenantMismatch as exc:
                raise RunTenantMismatchError(run_id) from exc
            except (DistributedRunNotFound, DistributedRunStoreUnavailable):
                shared = None
            if shared is not None:
                if shared.get("status") == "orphaned":
                    await self._mark_durable_orphaned(run_id, tenant_id)
                shared["durable_history"] = await self._durable_capability(
                    run_id,
                    tenant_id,
                )
                return shared

        durable = await self._get_durable(run_id=run_id, tenant_id=tenant_id)
        if durable is None:
            raise RunNotFoundError(run_id)
        durable["distributed_control"] = {
            "supported": False,
            "reason_code": "no_live_cluster_ownership",
        }
        durable["cancellable"] = False
        return durable

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool = True,
    ) -> list[dict[str, Any]]:
        async with self._lock:
            local_runs = [
                run
                for run in self._runs.values()
                if run.tenant_id == tenant_id
                and (
                    include_terminal
                    or run.status
                    in {ExecutionRunStatus.RUNNING, ExecutionRunStatus.CANCELLING}
                )
            ]

        merged: dict[str, dict[str, Any]] = {}
        for run in local_runs:
            snapshot = run.snapshot()
            snapshot["distributed_control"] = await self._distributed_capability(
                run.shared_registered
            )
            merged[run.run_id] = snapshot

        shared_available = await self._distributed_available()
        if shared_available:
            try:
                shared_runs = await self._distributed_store.list_runs(
                    tenant_id=tenant_id,
                    include_terminal=include_terminal,
                )
            except DistributedRunStoreUnavailable:
                shared_runs = []
                shared_available = False
            for snapshot in shared_runs:
                run_id = snapshot["run_id"]
                if snapshot.get("status") == "orphaned":
                    await self._mark_durable_orphaned(run_id, tenant_id)
                snapshot["durable_history"] = await self._durable_capability(
                    run_id,
                    tenant_id,
                )
                if run_id not in merged:
                    merged[run_id] = snapshot

        durable_runs = await self._list_durable(tenant_id, include_terminal)
        budget = self._settings.run_reconciliation_batch_size
        for durable in durable_runs:
            run_id = durable["run_id"]
            if run_id in merged:
                continue
            if (
                shared_available
                and durable.get("status") in self._DURABLE_ACTIVE
                and budget > 0
            ):
                budget -= 1
                try:
                    shared = await self._distributed_store.get(
                        run_id=run_id,
                        tenant_id=tenant_id,
                    )
                except DistributedRunNotFound:
                    await self._mark_durable_orphaned(run_id, tenant_id)
                    durable["status"] = "orphaned"
                except DistributedRunStoreUnavailable:
                    shared_available = False
                else:
                    shared["durable_history"] = durable["durable_history"]
                    merged[run_id] = shared
                    continue
            durable["distributed_control"] = {
                "supported": False,
                "reason_code": (
                    "no_live_cluster_ownership"
                    if shared_available
                    else "shared_redis_unavailable"
                ),
            }
            durable["cancellable"] = False
            merged[run_id] = durable

        return sorted(
            merged.values(),
            key=lambda item: item.get("started_at") or "",
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
                    await self._safe_request_durable_cancel(
                        run_id=run.run_id,
                        tenant_id=run.tenant_id,
                    )
                    run.task.cancel()
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

    async def _safe_request_durable_cancel(
        self,
        *,
        run_id: str,
        tenant_id: str,
        audit_event_id: str | None = None,
    ) -> None:
        if not self._settings.durable_run_history_enabled:
            return
        try:
            await self._durable_ledger.request_cancel(
                run_id=run_id,
                tenant_id=tenant_id,
                worker_id=self._settings.worker_id,
                audit_event_id=audit_event_id,
            )
        except (MedusaRunLedgerNotFound, MedusaRunLedgerConflict):
            return
        except Exception as exc:
            logger.error(
                "Medusa cancellation request could not be persisted durably",
                extra={
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "error_type": type(exc).__name__,
                },
            )

    async def _safe_mark_durable_terminal(
        self,
        run: ExecutionRun,
        *,
        status: str,
        completed_at: datetime | None = None,
        error_type: str | None = None,
        reason_code: str | None = None,
    ) -> None:
        try:
            await self._durable_ledger.mark_terminal(
                run_id=run.run_id,
                tenant_id=run.tenant_id,
                status=status,
                completed_at=completed_at or datetime.now(timezone.utc),
                worker_id=self._settings.worker_id,
                error_type=error_type,
                reason_code=reason_code,
            )
        except (MedusaRunLedgerNotFound, MedusaRunLedgerConflict) as exc:
            logger.warning(
                "Medusa durable terminal transition rejected",
                extra={
                    "run_id": run.run_id,
                    "status": status,
                    "error_type": type(exc).__name__,
                },
            )
        except Exception as exc:
            logger.error(
                "Medusa terminal state could not be persisted durably",
                extra={
                    "run_id": run.run_id,
                    "status": status,
                    "error_type": type(exc).__name__,
                },
            )

    async def _mark_durable_orphaned(self, run_id: str, tenant_id: str) -> None:
        if not self._settings.durable_run_history_enabled:
            return
        try:
            await self._durable_ledger.mark_terminal(
                run_id=run_id,
                tenant_id=tenant_id,
                status="orphaned",
                completed_at=datetime.now(timezone.utc),
                worker_id=None,
                reason_code="live_ownership_missing",
            )
        except (MedusaRunLedgerNotFound, MedusaRunLedgerConflict):
            return
        except Exception as exc:
            logger.error(
                "Medusa orphan reconciliation could not be persisted",
                extra={
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "error_type": type(exc).__name__,
                },
            )

    async def _reconcile_missing(self, *, run_id: str, tenant_id: str) -> None:
        durable = await self._get_durable(run_id=run_id, tenant_id=tenant_id)
        if durable and durable.get("status") in self._DURABLE_ACTIVE:
            await self._mark_durable_orphaned(run_id, tenant_id)

    async def _get_durable(
        self,
        *,
        run_id: str,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        if not self._settings.durable_run_history_enabled:
            return None
        try:
            return await self._durable_ledger.get(
                run_id=run_id,
                tenant_id=tenant_id,
            )
        except MedusaRunLedgerNotFound:
            return None
        except Exception as exc:
            logger.error(
                "Medusa durable run lookup unavailable",
                extra={
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "error_type": type(exc).__name__,
                },
            )
            return None

    async def _list_durable(
        self,
        tenant_id: str,
        include_terminal: bool,
    ) -> list[dict[str, Any]]:
        if not self._settings.durable_run_history_enabled:
            return []
        try:
            return await self._durable_ledger.list_runs(
                tenant_id=tenant_id,
                include_terminal=include_terminal,
                limit=self._settings.run_history_list_limit,
            )
        except Exception as exc:
            logger.error(
                "Medusa durable run listing unavailable",
                extra={
                    "tenant_id": tenant_id,
                    "error_type": type(exc).__name__,
                },
            )
            return []

    async def _durable_capability(
        self,
        run_id: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        if not self._settings.durable_run_history_enabled:
            return {
                "supported": False,
                "reason_code": "durable_run_history_disabled",
            }
        durable = await self._get_durable(run_id=run_id, tenant_id=tenant_id)
        if durable is None:
            return {
                "supported": False,
                "reason_code": "durable_history_unavailable",
            }
        return {"supported": True, "source": "postgresql"}

    async def _distributed_available(self) -> bool:
        if not self._settings.distributed_run_control_enabled:
            return False
        try:
            return await self._distributed_store.available()
        except Exception:
            return False

    async def _distributed_capability(
        self,
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
    """Return the process-wide Medusa execution authority."""

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
