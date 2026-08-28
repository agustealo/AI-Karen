"""Canonical execution authority for Agent Medusa runs.

Concrete asyncio tasks remain owned by the worker process that executes them.
Redis owns transient cluster coordination. PostgreSQL owns durable execution
history. Neither persistence layer may directly cancel a concrete task.
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
from ai_karen_engine.persistence.repositories.medusa_run_repository import (
    MedusaRunRepositoryConflict,
    MedusaRunRepositoryUnavailable,
    SqlMedusaRunRepository,
)

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
    """Canonical worker-local lifecycle states for one Medusa execution run."""

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
    request_id: str | None = None
    session_id: str | None = None
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
            "request_id": self.request_id or self.run_id,
            "session_id": self.session_id,
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
                "persisted": self.durable_registered,
            },
            "response_source": "worker_local_execution",
        }


class RunNotFoundError(LookupError):
    """Raised when a requested execution run is unknown."""


class RunTenantMismatchError(PermissionError):
    """Raised when an operator crosses tenant scope."""


class RunNotCancellableError(RuntimeError):
    """Raised when a terminal, orphaned, or cancelling run is cancelled."""


class MedusaRunManager:
    """Own local tasks while coordinating live and durable run truth."""

    def __init__(
        self,
        *,
        terminal_retention: int = 256,
        settings: AgentMedusaRuntimeSettings | None = None,
        distributed_store: DistributedRunStore | None = None,
        durable_repository: Any | None = None,
    ) -> None:
        self._runs: dict[str, ExecutionRun] = {}
        self._terminal_order: list[str] = []
        self._terminal_retention = max(1, terminal_retention)
        self._lock = asyncio.Lock()
        self._settings = settings or get_agent_medusa_runtime_settings()
        self._distributed_store = distributed_store or RedisDistributedRunStore(
            settings=self._settings
        )
        self._durable_repository = durable_repository or SqlMedusaRunRepository()
        self._reconciliation_lock = asyncio.Lock()
        self._reconciliation_attempted = False

    async def register(
        self,
        *,
        run_id: str,
        correlation_id: str,
        tenant_id: str,
        user_id: str,
        task: asyncio.Task[Any],
        request_id: str | None = None,
        session_id: str | None = None,
        policy_decision_id: str | None = None,
    ) -> ExecutionRun:
        await self._ensure_reconciled()
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
                request_id=request_id or run_id,
                session_id=session_id,
                policy_decision_id=policy_decision_id,
            )
            self._runs[run_id] = run

        if await self._durable_available():
            try:
                await self._durable_repository.register(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    correlation_id=correlation_id,
                    request_id=request_id or run_id,
                    session_id=session_id,
                    policy_decision_id=policy_decision_id,
                    worker_id=self._settings.worker_id,
                    started_at=run.started_at,
                )
            except MedusaRunRepositoryUnavailable:
                logger.warning(
                    "medusa_durable_run_registration_unavailable",
                    extra={"run_id": run_id, "correlation_id": correlation_id},
                )
            else:
                run.durable_registered = True

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
                if run.durable_registered:
                    try:
                        await self._durable_repository.mark_terminal(
                            run_id=run_id,
                            tenant_id=tenant_id,
                            worker_id=self._settings.worker_id,
                            status="failed",
                            completed_at=datetime.now(timezone.utc),
                            error_type="DistributedRegistrationFailed",
                        )
                    except Exception:
                        logger.exception(
                            "medusa_durable_compensation_failed",
                            extra={"run_id": run_id},
                        )
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
        durable_registered = False
        tenant_id: str | None = None
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
            durable_registered = run.durable_registered
            tenant_id = run.tenant_id
            if run_id not in self._terminal_order:
                self._terminal_order.append(run_id)
            self._prune_locked()

        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        if durable_registered and tenant_id is not None:
            try:
                persisted = await self._durable_repository.mark_terminal(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    worker_id=self._settings.worker_id,
                    status=status.value,
                    completed_at=completed_at,
                    error_type=error_type,
                )
                if not persisted:
                    logger.warning(
                        "medusa_durable_terminal_transition_rejected",
                        extra={"run_id": run_id, "status": status.value},
                    )
            except Exception:
                logger.exception(
                    "medusa_durable_terminal_write_failed",
                    extra={"run_id": run_id, "status": status.value},
                )

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

    async def cancel(
        self,
        *,
        run_id: str,
        tenant_id: str,
        audit_event_ref: str | None = None,
    ) -> dict[str, Any]:
        await self._ensure_reconciled()
        local_task: asyncio.Task[Any] | None = None
        local_shared = False
        local_durable = False
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
                local_durable = run.durable_registered

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
            if local_durable:
                await self._persist_cancellation_request(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    audit_event_ref=audit_event_ref,
                )
            local_task.cancel()
            return await self.get(run_id=run_id, tenant_id=tenant_id)

        if not await self._distributed_available():
            durable = await self._get_durable(run_id=run_id, tenant_id=tenant_id)
            if durable is not None:
                raise RunNotCancellableError(
                    f"Run {run_id} is durable-only while shared Redis authority is unavailable"
                )
            raise RunNotFoundError(run_id)
        try:
            snapshot = await self._distributed_store.request_cancel(
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

        if await self._durable_available():
            await self._persist_cancellation_request(
                run_id=run_id,
                tenant_id=tenant_id,
                audit_event_ref=audit_event_ref,
            )
        snapshot["durable_history"] = await self._durable_capability(
            run_id=run_id,
            tenant_id=tenant_id,
        )
        return snapshot

    async def link_audit_event(
        self,
        *,
        run_id: str,
        tenant_id: str,
        audit_event_ref: str,
    ) -> None:
        """Attach an audit correlation token without moving audit authority."""

        if not await self._durable_available():
            return
        try:
            await self._durable_repository.link_audit_event(
                run_id=run_id,
                tenant_id=tenant_id,
                audit_event_ref=audit_event_ref,
            )
        except Exception:
            logger.exception(
                "medusa_durable_audit_link_failed",
                extra={"run_id": run_id, "audit_event_ref": audit_event_ref},
            )

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        await self._ensure_reconciled()
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

        if await self._distributed_available():
            try:
                shared = await self._distributed_store.get(
                    run_id=run_id,
                    tenant_id=tenant_id,
                )
            except DistributedRunNotFound:
                shared = None
            except DistributedRunTenantMismatch as exc:
                raise RunTenantMismatchError(run_id) from exc
            except DistributedRunStoreUnavailable:
                shared = None
            if shared is not None:
                shared["durable_history"] = await self._durable_capability(
                    run_id=run_id,
                    tenant_id=tenant_id,
                )
                return shared

        durable = await self._get_durable(run_id=run_id, tenant_id=tenant_id)
        if durable is not None:
            durable["distributed_control"] = {
                "supported": False,
                "reason_code": "durable_history_is_not_live_control_authority",
            }
            durable["cancellable"] = False
            return durable
        raise RunNotFoundError(run_id)

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool = True,
    ) -> list[dict[str, Any]]:
        await self._ensure_reconciled()
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
                    snapshot["durable_history"] = await self._durable_capability(
                        run_id=run_id,
                        tenant_id=tenant_id,
                    )
                    merged[run_id] = snapshot

        if await self._durable_available():
            try:
                durable_runs = await self._durable_repository.list_runs(
                    tenant_id=tenant_id,
                    include_terminal=include_terminal,
                    limit=self._settings.run_history_list_limit,
                )
            except Exception:
                logger.exception(
                    "medusa_durable_history_list_failed",
                    extra={"tenant_id": tenant_id},
                )
                durable_runs = []
            for durable in durable_runs:
                run_id = str(durable["run_id"])
                if run_id in merged:
                    continue
                durable["distributed_control"] = {
                    "supported": False,
                    "reason_code": "durable_history_is_not_live_control_authority",
                }
                durable["cancellable"] = False
                merged[run_id] = durable

        return sorted(
            merged.values(),
            key=lambda item: item.get("started_at") or "",
            reverse=True,
        )

    async def reconcile_durable_history(self) -> dict[str, Any]:
        """Boundedly reconcile nonterminal PostgreSQL history against Redis truth."""

        if not await self._durable_available():
            return {"attempted": False, "reason_code": "durable_history_unavailable"}
        if not await self._distributed_available():
            return {
                "attempted": False,
                "reason_code": "shared_redis_unavailable",
                "orphaned": 0,
                "terminal_repaired": 0,
                "cancellation_repaired": 0,
            }

        records = await self._durable_repository.list_reconcilable(
            limit=self._settings.run_reconciliation_batch_size
        )
        orphaned = 0
        terminal_repaired = 0
        cancellation_repaired = 0
        unchanged = 0
        for record in records:
            run_id = str(record["run_id"])
            tenant_id = str(record["tenant_id"])
            try:
                shared = await self._distributed_store.get(
                    run_id=run_id,
                    tenant_id=tenant_id,
                )
            except DistributedRunNotFound:
                if await self._durable_repository.mark_orphaned(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    expected_worker_id=str(record.get("owner_worker_id") or "") or None,
                ):
                    orphaned += 1
                continue
            except DistributedRunStoreUnavailable:
                return {
                    "attempted": False,
                    "reason_code": "shared_redis_unavailable",
                    "orphaned": orphaned,
                    "terminal_repaired": terminal_repaired,
                    "cancellation_repaired": cancellation_repaired,
                }
            except DistributedRunTenantMismatch:
                logger.error(
                    "medusa_reconciliation_tenant_mismatch",
                    extra={"run_id": run_id, "tenant_id": tenant_id},
                )
                unchanged += 1
                continue

            shared_status = str(shared.get("status") or "")
            if shared_status == "orphaned":
                if await self._durable_repository.mark_orphaned(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    expected_worker_id=str(record.get("owner_worker_id") or "") or None,
                ):
                    orphaned += 1
            elif shared_status in {"cancelled", "completed", "failed"}:
                completed_raw = shared.get("completed_at")
                completed_at = self._parse_datetime(completed_raw)
                if await self._durable_repository.reconcile_terminal(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    status=shared_status,
                    completed_at=completed_at,
                    error_type=shared.get("error_type"),
                ):
                    terminal_repaired += 1
            elif shared_status == "cancelling" and record.get("status") == "running":
                try:
                    await self._durable_repository.request_cancel(
                        run_id=run_id,
                        tenant_id=tenant_id,
                    )
                except MedusaRunRepositoryConflict:
                    unchanged += 1
                else:
                    cancellation_repaired += 1
            else:
                unchanged += 1

        return {
            "attempted": True,
            "batch_size": len(records),
            "orphaned": orphaned,
            "terminal_repaired": terminal_repaired,
            "cancellation_repaired": cancellation_repaired,
            "unchanged": unchanged,
        }

    async def _ensure_reconciled(self) -> None:
        if self._reconciliation_attempted:
            return
        async with self._reconciliation_lock:
            if self._reconciliation_attempted:
                return
            try:
                summary = await self.reconcile_durable_history()
                logger.info("medusa_durable_reconciliation", extra=summary)
            except Exception:
                logger.exception("medusa_durable_reconciliation_failed")
            finally:
                self._reconciliation_attempted = True

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
                    if run.durable_registered:
                        await self._persist_cancellation_request(
                            run_id=run.run_id,
                            tenant_id=run.tenant_id,
                            audit_event_ref=None,
                        )
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

    async def _persist_cancellation_request(
        self,
        *,
        run_id: str,
        tenant_id: str,
        audit_event_ref: str | None,
    ) -> None:
        try:
            await self._durable_repository.request_cancel(
                run_id=run_id,
                tenant_id=tenant_id,
                audit_event_ref=audit_event_ref,
            )
        except (LookupError, MedusaRunRepositoryConflict):
            logger.warning(
                "medusa_durable_cancel_transition_rejected",
                extra={"run_id": run_id, "tenant_id": tenant_id},
            )
        except Exception:
            logger.exception(
                "medusa_durable_cancel_write_failed",
                extra={"run_id": run_id, "tenant_id": tenant_id},
            )

    async def _get_durable(
        self,
        *,
        run_id: str,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        if not await self._durable_available():
            return None
        try:
            return await self._durable_repository.get(
                run_id=run_id,
                tenant_id=tenant_id,
            )
        except Exception:
            logger.exception(
                "medusa_durable_history_get_failed",
                extra={"run_id": run_id, "tenant_id": tenant_id},
            )
            return None

    async def _durable_capability(
        self,
        *,
        run_id: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        durable = await self._get_durable(run_id=run_id, tenant_id=tenant_id)
        if durable is None:
            return {
                "supported": False,
                "persisted": False,
                "reason_code": "durable_history_unavailable_or_missing",
            }
        return {"supported": True, "persisted": True}

    async def _durable_available(self) -> bool:
        if not self._settings.durable_run_history_enabled:
            return False
        try:
            return bool(await self._durable_repository.available())
        except Exception:
            return False

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

    def _parse_datetime(self, value: Any) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            parsed = value
        else:
            parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

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
