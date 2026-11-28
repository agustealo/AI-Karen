"""Canonical execution authority for Agent Medusa runs.

Concrete asyncio tasks remain owned by the worker process that executes them.
Redis provides live cluster coordination and cancellation. PostgreSQL provides
long-lived run history. Reconciliation flows from Redis live truth into durable
history, never the reverse, and neither storage layer becomes task authority.
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
from ai_karen_engine.core.expression.errors import ExecutionAdmissionRejected
from ai_karen_engine.core.logging import get_logger

from ..telemetry.metrics import record_retention_event
from .distributed_run_store import (
    DistributedRunAdmissionCancelled,
    DistributedRunAdmissionRejected,
    DistributedRunNotCancellable,
    DistributedRunNotFound,
    DistributedRunOwnershipLost,
    DistributedRunStore,
    DistributedRunStoreUnavailable,
    DistributedRunTenantMismatch,
    RedisDistributedRunStore,
)
from .durable_run_ledger import (
    DurableRunLedger,
    DurableRunLedgerConflict,
    DurableRunLedgerUnavailable,
    PostgresDurableRunLedger,
    _canonical_tenant_id,
)

logger = get_logger(__name__)


class ExecutionRunStatus(str, Enum):
    """Canonical lifecycle states for one worker-local Medusa execution run."""

    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ORPHANED = "orphaned"

    @classmethod
    def for_response(cls, outcome_status: str) -> ExecutionRunStatus:
        """Map a normalized response outcome to its proposed lifecycle."""
        if outcome_status in {"success", "partial", "degraded"}:
            return cls.COMPLETED
        if outcome_status in {"error", "timeout"}:
            return cls.FAILED
        raise ValueError(f"Unsupported Medusa outcome status: {outcome_status}")


@dataclass
class ExecutionRun:
    """Mutable worker-local record for one coordinator request."""

    run_id: str
    correlation_id: str
    request_id: str
    session_id: str | None
    policy_decision_id: str | None
    tenant_id: str
    user_id: str
    task: asyncio.Task[Any]
    status: ExecutionRunStatus = ExecutionRunStatus.RUNNING
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    error_type: str | None = None
    outcome_status: str | None = None
    shared_registered: bool = False
    durable_registered: bool = False
    heartbeat_task: asyncio.Task[None] | None = field(default=None, repr=False)
    cancel_admission_pending: bool = field(default=False, repr=False)
    cancel_signal_sent: bool = field(default=False, repr=False)
    shared_ownership_lost: bool = field(default=False, repr=False)
    terminal_pending: bool = field(default=False, repr=False)
    terminal_unconfirmed: bool = field(default=False, repr=False)
    terminal_attempted_at: datetime | None = field(default=None, repr=False)
    terminal_recovered: bool = field(default=False, repr=False)
    retention_pending: bool = field(default=False, repr=False)

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "correlation_id": self.correlation_id,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "policy_decision_id": self.policy_decision_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "error_type": self.error_type,
            "outcome_status": self.outcome_status,
            "cancellable": (
                self.status is ExecutionRunStatus.RUNNING
                and not self.cancel_admission_pending
                and not self.terminal_pending
            ),
            "durable": self.durable_registered,
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
        durable_ledger: DurableRunLedger | None = None,
    ) -> None:
        self._runs: dict[str, ExecutionRun] = {}
        self._terminal_order: list[str] = []
        self._terminal_retention = max(1, terminal_retention)
        self._lock = asyncio.Lock()
        self._settings = settings or get_agent_medusa_runtime_settings()
        self._distributed_store = distributed_store or RedisDistributedRunStore(
            settings=self._settings
        )
        self._durable_ledger = durable_ledger or PostgresDurableRunLedger()

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
        request_id = request_id or run_id
        started_at = datetime.now(timezone.utc)
        async with self._lock:
            existing = self._runs.get(run_id)
            if existing is not None and (
                existing.terminal_unconfirmed
                or existing.status
                in {
                    ExecutionRunStatus.RUNNING,
                    ExecutionRunStatus.CANCELLING,
                    ExecutionRunStatus.ORPHANED,
                }
            ):
                raise ExecutionAdmissionRejected("medusa_local_registration_conflict")
            run = ExecutionRun(
                run_id=run_id,
                correlation_id=correlation_id,
                request_id=request_id,
                session_id=session_id,
                policy_decision_id=policy_decision_id,
                tenant_id=tenant_id,
                user_id=user_id,
                task=task,
                started_at=started_at,
            )
            self._runs[run_id] = run

        try:
            if self._settings.durable_run_ledger_enabled:
                await self._durable_ledger.register(
                    run_id=run_id,
                    correlation_id=correlation_id,
                    request_id=request_id,
                    session_id=session_id,
                    policy_decision_id=policy_decision_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    worker_id=self._settings.worker_id,
                    created_at=started_at,
                )
                run.durable_registered = True
        except asyncio.CancelledError:
            await self._finish_cancelled_admission(
                run,
                error_type="DurableRegistrationUnconfirmed",
                persist_failure=False,
            )
            raise
        except Exception as exc:
            reason = (
                "medusa_durable_registration_conflict"
                if isinstance(exc, DurableRunLedgerConflict)
                else "medusa_durable_registration_unconfirmed"
            )
            # A lost INSERT acknowledgement is not ownership proof.
            await self._retire_rejected_registration(
                run, error_type=reason, persist_failure=False
            )
            raise ExecutionAdmissionRejected(reason) from None

        guarded = (
            self._settings.distributed_run_control_enabled
            and self._settings.run_redis_admission_reserve_bytes > 0
        )
        # A guarded admission must reach the shared registration boundary.
        # A failed PING cannot silently bypass the reserve via durable-only mode.
        registration_attempted = False
        try:
            if guarded or await self._distributed_available():
                try:
                    registration_attempted = True
                    await self._distributed_store.register(
                        run_id=run_id,
                        correlation_id=correlation_id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        worker_id=self._settings.worker_id,
                        started_at=started_at,
                    )
                except DistributedRunStoreUnavailable:
                    if guarded:
                        raise DistributedRunAdmissionRejected(
                            "redis_capacity_unverified",
                        ) from None
                    logger.warning(
                        "Medusa distributed coordination unavailable during registration",
                        extra={"run_id": run_id, "correlation_id": correlation_id},
                    )
                else:
                    run.shared_registered = True
        except asyncio.CancelledError as exc:
            # Only the store's pre-write cancellation proves no shared mutation.
            # An unclassified cancellation during register is also uncertain.
            uncertain = registration_attempted and not isinstance(
                exc, DistributedRunAdmissionCancelled
            )
            await self._finish_cancelled_admission(
                run,
                error_type=(
                    "AdmissionCancelledRegistrationUnconfirmed"
                    if uncertain
                    else "AdmissionCancelledBeforeRegistration"
                ),
            )
            raise
        except Exception as exc:
            if isinstance(exc, DistributedRunAdmissionRejected):
                logger.warning(
                    "medusa_run_admission_rejected",
                    extra={
                        "run_id": run_id,
                        "correlation_id": correlation_id,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "reason_code": exc.reason_code,
                    },
                )
            try:
                if run.durable_registered:
                    await self._safe_mark_durable_terminal(
                        run=run,
                        status=ExecutionRunStatus.FAILED,
                        completed_at=datetime.now(timezone.utc),
                        error_type=type(exc).__name__,
                    )
            except Exception as cleanup_error:
                if not isinstance(exc, DistributedRunAdmissionRejected):
                    raise
                # A ledger outage must not replace a terminal admission
                # denial with a generic error eligible for model fallback.
                logger.error(
                    "medusa_admission_failure_persistence_unconfirmed",
                    extra={
                        "run_id": run_id,
                        "correlation_id": correlation_id,
                        "tenant_id": tenant_id,
                        "error_type": type(cleanup_error).__name__,
                    },
                )
            finally:
                async with self._lock:
                    if self._runs.get(run_id) is run:
                        self._runs.pop(run_id, None)
            raise

        if run.durable_registered:
            try:
                await self._durable_ledger.mark_running(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    worker_id=self._settings.worker_id,
                    started_at=started_at,
                    shared_registration=(
                        "acknowledged"
                        if run.shared_registered
                        else (
                            "unavailable"
                            if self._settings.distributed_run_control_enabled
                            else "not_configured"
                        )
                    ),
                )
            except asyncio.CancelledError:
                await self._finish_cancelled_admission(
                    run,
                    error_type="DurableRunningTransitionUnconfirmed",
                    persist_failure=False,
                )
                raise
            except Exception as exc:
                reason = (
                    "medusa_durable_running_conflict"
                    if isinstance(exc, DurableRunLedgerConflict)
                    else "medusa_durable_running_unconfirmed"
                )
                # Preserve both stores for authoritative repair. A failed
                # acknowledgement or conflict is not permission to overwrite
                # either record with a terminal receipt.
                await self._retire_rejected_registration(
                    run, error_type=reason, persist_failure=False
                )
                raise ExecutionAdmissionRejected(reason) from None

        if run.shared_registered:
            run.heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(run),
                name=f"medusa-run-heartbeat:{run_id}",
            )
        return run

    async def _finish_cancelled_admission(
        self,
        run: ExecutionRun,
        *,
        error_type: str,
        persist_failure: bool = True,
    ) -> None:
        cleanup = asyncio.create_task(
            self._retire_rejected_registration(
                run, error_type=error_type, persist_failure=persist_failure
            ),
        )
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                continue
        cleanup.result()

    async def _retire_rejected_registration(
        self,
        run: ExecutionRun,
        *,
        error_type: str,
        persist_failure: bool = True,
    ) -> None:
        """Close an unstarted task without asserting shared registration rollback."""
        try:
            if not persist_failure:
                logger.warning(
                    "medusa_durable_admission_denied",
                    extra={
                        "run_id": run.run_id,
                        "correlation_id": run.correlation_id,
                        "request_id": run.request_id,
                        "tenant_id": run.tenant_id,
                        "user_id": run.user_id,
                        "reason_code": error_type,
                        "durable_registered": run.durable_registered,
                        "shared_registered": run.shared_registered,
                    },
                )
            elif run.durable_registered:
                await self._safe_mark_durable_terminal(
                    run=run,
                    status=ExecutionRunStatus.FAILED,
                    completed_at=datetime.now(timezone.utc),
                    error_type=error_type,
                )
        except Exception as exc:
            # Preserve cancellation; durable closure is explicitly unconfirmed.
            logger.error(
                "medusa_admission_cancellation_persistence_unconfirmed",
                extra={
                    "run_id": run.run_id,
                    "correlation_id": run.correlation_id,
                    "tenant_id": run.tenant_id,
                    "error_type": type(exc).__name__,
                },
            )
        finally:
            async with self._lock:
                if self._runs.get(run.run_id) is run:
                    self._runs.pop(run.run_id, None)

    async def mark_response(
        self, run_id: str, outcome_status: str
    ) -> ExecutionRunStatus:
        """Return the resolved lifecycle, not merely the proposed response."""

        normalized = str(outcome_status or "").strip().lower()
        lifecycle = ExecutionRunStatus.for_response(normalized)
        resolved = await self._mark_terminal(
            run_id,
            lifecycle,
            outcome_status=normalized,
            error_type=(
                None
                if lifecycle is ExecutionRunStatus.COMPLETED
                else f"Response{normalized.title()}"
            ),
        )
        if resolved is None:
            raise RunNotFoundError(run_id)
        return resolved

    async def mark_completed(self, run_id: str) -> None:
        await self._mark_terminal(
            run_id,
            ExecutionRunStatus.COMPLETED,
            outcome_status="success",
        )

    async def mark_failed(
        self, run_id: str, exc: BaseException
    ) -> ExecutionRunStatus | None:
        return await self._mark_terminal(
            run_id,
            ExecutionRunStatus.FAILED,
            error_type=type(exc).__name__,
            outcome_status="error",
        )

    async def mark_cancelled(self, run_id: str) -> ExecutionRunStatus | None:
        return await self._mark_terminal(
            run_id,
            ExecutionRunStatus.CANCELLED,
            outcome_status="cancelled",
        )

    async def mark_retirement_unverified(self, run_id: str) -> None:
        """Close lost task ownership, not the underlying native execution.

        Reuse the existing orphaned ledger state and owner-fenced lease
        retirement. The timestamp records lifecycle closure only; no task
        outcome or verified cessation is implied.
        """
        await self._mark_terminal(
            run_id,
            ExecutionRunStatus.ORPHANED,
            error_type="NativeRetirementUnverified",
        )

    async def _mark_terminal(
        self,
        run_id: str,
        status: ExecutionRunStatus,
        *,
        error_type: str | None = None,
        outcome_status: str | None = None,
    ) -> ExecutionRunStatus | None:
        heartbeat_task: asyncio.Task[None] | None = None
        completed_at = datetime.now(timezone.utc)
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            if run.shared_ownership_lost or run.terminal_unconfirmed:
                # The worker has no authority to publish any terminal outcome.
                # Retain the active task identity until its finalizer observes
                # local retirement; never infer native cessation from this.
                if (
                    run.task.done() or run.task is asyncio.current_task()
                ) and run_id not in self._terminal_order:
                    self._terminal_order.append(run_id)
                    self._prune_locked()
                return ExecutionRunStatus.ORPHANED
            if run.terminal_pending:
                raise DistributedRunStoreUnavailable("terminal_transition_in_progress")
            if (
                run.status is ExecutionRunStatus.CANCELLING
                and status is not ExecutionRunStatus.ORPHANED
            ):
                status = ExecutionRunStatus.CANCELLED
                outcome_status = "cancelled"
                error_type = None
            elif run.status in {
                ExecutionRunStatus.COMPLETED,
                ExecutionRunStatus.FAILED,
                ExecutionRunStatus.CANCELLED,
                ExecutionRunStatus.ORPHANED,
            }:
                return run.status
            heartbeat_task = run.heartbeat_task
            run.heartbeat_task = None
            run.terminal_pending = True
            run.terminal_attempted_at = completed_at

        if run.shared_registered:
            try:
                await self._stop_terminal_heartbeat(heartbeat_task)

                async def authorize(
                    proposed: str, error: str | None, outcome: str | None
                ) -> str:
                    try:
                        return await asyncio.wait_for(
                            self._distributed_store.mark_terminal(
                                run_id=run_id,
                                tenant_id=run.tenant_id,
                                worker_id=self._settings.worker_id,
                                status=proposed,
                                completed_at=completed_at,
                                error_type=error,
                                outcome_status=outcome,
                                durable_arbitrated=run.durable_registered,
                            ),
                            timeout=self._settings.run_lease_ttl_seconds,
                        )
                    except asyncio.TimeoutError as exc:
                        raise DistributedRunStoreUnavailable(
                            "shared_terminal_commit_unconfirmed"
                        ) from exc

                if run.durable_registered:
                    # The ledger holds its existing row lock across the bounded
                    # shared authorization, including cancellation resolution.
                    resolved = await self._durable_ledger.mark_terminal(
                        run_id=run_id,
                        tenant_id=run.tenant_id,
                        worker_id=self._settings.worker_id,
                        status=status.value,
                        completed_at=completed_at,
                        error_type=error_type,
                        outcome_status=outcome_status,
                        authorize_terminal=authorize,
                    )
                else:
                    resolved = await authorize(status.value, error_type, outcome_status)
                if resolved != status.value:
                    if resolved != "cancelled" or status not in {
                        ExecutionRunStatus.COMPLETED,
                        ExecutionRunStatus.FAILED,
                    }:
                        raise DistributedRunStoreUnavailable(
                            "shared_terminal_resolution_mismatch"
                        )
                    status = ExecutionRunStatus.CANCELLED
                    outcome_status = "cancelled"
                    error_type = None
                if run.durable_registered:
                    confirmed_receipt = {
                        "run_id": run.run_id,
                        "tenant_id": _canonical_tenant_id(run.tenant_id),
                        "owner_worker_id": self._settings.worker_id,
                        "correlation_id": run.correlation_id,
                        "user_id": run.user_id,
                        "status": status.value,
                        "completed_at": completed_at.isoformat(),
                        "error_type": error_type,
                        "outcome_status": outcome_status,
                    }
                    acknowledged = await self._release_terminal_retention(
                        run.tenant_id, confirmed_receipt
                    )
                    run.retention_pending = not acknowledged
                async with self._lock:
                    self._publish_terminal_locked(
                        run, status, completed_at, error_type, outcome_status
                    )
                    run.terminal_pending = False
                return status
            except (Exception, asyncio.CancelledError) as exc:
                # A failed response may follow a committed storage operation.
                # Never report the proposed result or replay the workload.
                async with self._lock:
                    run.terminal_pending = False
                    run.shared_ownership_lost = isinstance(
                        exc, (DistributedRunNotFound, DistributedRunOwnershipLost)
                    )
                    run.terminal_unconfirmed = not run.shared_ownership_lost
                    run.status = ExecutionRunStatus.ORPHANED
                    run.completed_at = None
                    run.outcome_status = None
                    run.error_type = (
                        "WorkerLeaseExpired"
                        if run.shared_ownership_lost
                        else "TerminalCommitUnconfirmed"
                    )
                    if run.task is not asyncio.current_task():
                        self._signal_task_once_locked(run)
                    if run.task.done() or run.task is asyncio.current_task():
                        if run_id not in self._terminal_order:
                            self._terminal_order.append(run_id)
                            self._prune_locked()
                logger.warning(
                    "Medusa terminal authority unconfirmed",
                    extra={
                        "run_id": run_id,
                        "tenant_id": run.tenant_id,
                        "error_type": type(exc).__name__,
                    },
                )
                if isinstance(exc, asyncio.CancelledError):
                    raise
                return ExecutionRunStatus.ORPHANED

        try:
            await self._stop_terminal_heartbeat(heartbeat_task)
            if run.durable_registered:
                # Even without Redis, a registered durable run must not expose
                # a proposed result before its persistence is confirmed.
                await self._durable_ledger.mark_terminal(
                    run_id=run_id,
                    tenant_id=run.tenant_id,
                    worker_id=self._settings.worker_id,
                    status=status.value,
                    completed_at=completed_at,
                    error_type=error_type,
                    outcome_status=outcome_status,
                )
            async with self._lock:
                self._publish_terminal_locked(
                    run, status, completed_at, error_type, outcome_status
                )
                run.terminal_pending = False
            return status
        except (Exception, asyncio.CancelledError) as exc:
            async with self._lock:
                run.terminal_pending = False
                run.terminal_unconfirmed = True
                run.status = ExecutionRunStatus.ORPHANED
                run.completed_at = None
                run.error_type = "TerminalCommitUnconfirmed"
                run.outcome_status = None
                if run.task is not asyncio.current_task():
                    self._signal_task_once_locked(run)
                if (
                    run.task.done() or run.task is asyncio.current_task()
                ) and run_id not in self._terminal_order:
                    self._terminal_order.append(run_id)
                    self._prune_locked()
            logger.warning(
                "Medusa local terminal persistence unconfirmed",
                extra={
                    "run_id": run_id,
                    "tenant_id": run.tenant_id,
                    "error_type": type(exc).__name__,
                },
            )
            if isinstance(exc, asyncio.CancelledError):
                raise
            return ExecutionRunStatus.ORPHANED

    def _publish_terminal_locked(
        self,
        run: ExecutionRun,
        status: ExecutionRunStatus,
        completed_at: datetime,
        error_type: str | None,
        outcome_status: str | None,
    ) -> None:
        run.status = status
        run.completed_at = completed_at
        run.error_type = error_type
        run.outcome_status = outcome_status
        if run.run_id not in self._terminal_order:
            self._terminal_order.append(run.run_id)
        self._prune_locked()

    @staticmethod
    async def _stop_terminal_heartbeat(
        heartbeat_task: asyncio.Task[None] | None,
    ) -> None:
        if heartbeat_task is not None and heartbeat_task is not asyncio.current_task():
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)

    async def _admit_local_cancellation(
        self,
        run: ExecutionRun,
        *,
        audit_event_ref: str | None = None,
        allow_existing: bool = False,
    ) -> bool:
        """Reserve one admission; publish cancellation only after durable acceptance.

        A terminal transition may win while storage is pending. In that case
        the late admission cannot change its outcome or signal the retired task.
        """
        async with self._lock:
            if self._runs.get(run.run_id) is not run or run.terminal_pending:
                return False
            if run.status is ExecutionRunStatus.CANCELLING:
                return allow_existing
            if (
                run.status is not ExecutionRunStatus.RUNNING
                or run.cancel_admission_pending
            ):
                return False
            run.cancel_admission_pending = True

        accepted = False
        try:
            if run.durable_registered:
                try:
                    await self._durable_ledger.mark_cancelling(
                        run_id=run.run_id,
                        tenant_id=run.tenant_id,
                        requested_at=datetime.now(timezone.utc),
                        audit_event_ref=audit_event_ref,
                        source="admin_cancel" if audit_event_ref else "runtime",
                    )
                except (DurableRunLedgerConflict, DurableRunLedgerUnavailable):
                    logger.exception(
                        "Medusa durable cancellation transition failed",
                        extra={"run_id": run.run_id, "tenant_id": run.tenant_id},
                    )
                    if self._settings.durable_run_ledger_required:
                        raise
            accepted = True
        finally:
            async with self._lock:
                run.cancel_admission_pending = False
                if (
                    accepted
                    and self._runs.get(run.run_id) is run
                    and run.status is ExecutionRunStatus.RUNNING
                    and not run.terminal_pending
                ):
                    run.status = ExecutionRunStatus.CANCELLING
                else:
                    accepted = False
        return accepted

    async def _signal_local_cancellation(self, run: ExecutionRun) -> None:
        """Signal only the still-owned, admitted task, never a retired run."""
        async with self._lock:
            if (
                self._runs.get(run.run_id) is run
                and run.status is ExecutionRunStatus.CANCELLING
                and not run.terminal_pending
            ):
                self._signal_task_once_locked(run)

    @staticmethod
    def _signal_task_once_locked(run: ExecutionRun) -> None:
        # Cleanup may consume CancelledError and call uncancel().
        # Do not interrupt it with a second runtime-owned signal.
        if not run.task.done() and not run.cancel_signal_sent:
            run.cancel_signal_sent = True
            if not run.task.cancelling():
                run.task.cancel()

    async def _record_shared_ownership_loss(self, run: ExecutionRun) -> None:
        """Fence a definitively rejected lease without writing as its owner."""
        async with self._lock:
            if (
                self._runs.get(run.run_id) is not run
                or run.terminal_pending
                or run.status
                not in {
                    ExecutionRunStatus.RUNNING,
                    ExecutionRunStatus.CANCELLING,
                }
            ):
                return
            run.shared_ownership_lost = True
            run.status = ExecutionRunStatus.ORPHANED
            run.completed_at = None
            run.error_type = "WorkerLeaseExpired"
            run.outcome_status = None
            run.heartbeat_task = None
            # Stop cooperatively, not a user cancellation acknowledgement.
            self._signal_task_once_locked(run)
            if run.task.done() and run.run_id not in self._terminal_order:
                self._terminal_order.append(run.run_id)
                self._prune_locked()
        logger.warning(
            "Medusa run live ownership lost",
            extra={"run_id": run.run_id, "tenant_id": run.tenant_id},
        )

    async def cancel(
        self,
        *,
        run_id: str,
        tenant_id: str,
        audit_event_ref: str | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            local_run = self._runs.get(run_id)
            if local_run is not None and local_run.tenant_id != tenant_id:
                raise RunTenantMismatchError(run_id)

        if local_run is not None:
            if not await self._admit_local_cancellation(
                local_run, audit_event_ref=audit_event_ref
            ):
                raise RunNotCancellableError(f"Run {run_id} is not cancellable")
            try:
                if local_run.shared_registered:
                    try:
                        await self._distributed_store.request_cancel(
                            run_id=run_id,
                            tenant_id=tenant_id,
                        )
                    except DistributedRunStoreUnavailable:
                        logger.warning(
                            "Shared cancel state unavailable; cancelling local owner task directly",
                            extra={"run_id": run_id},
                        )
                    except DistributedRunNotCancellable:
                        pass
                await self._signal_local_cancellation(local_run)
            except asyncio.CancelledError:
                # Requester disconnect does not revoke already admitted intent.
                # Preserve the caller's cancellation, but signal the owned task.
                await self._signal_local_cancellation(local_run)
                raise
            return await self.get(run_id=run_id, tenant_id=tenant_id)

        if await self._distributed_available():
            durable_accepted = False
            try:
                # Redis owns the live lease. Validate the tenant, owner lease,
                # and running status before changing durable history. This
                # read is advisory; request_cancel repeats the Redis checks
                # atomically after PostgreSQL has accepted the transition.
                live = await self._distributed_store.get(
                    run_id=run_id,
                    tenant_id=tenant_id,
                )
                if not live.get("cancellable", False):
                    raise RunNotCancellableError(
                        f"Run {run_id} is {live['status']}, not cancellable"
                    )
                if self._settings.durable_run_ledger_required:
                    await self._durable_ledger.mark_cancelling(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        requested_at=datetime.now(timezone.utc),
                        audit_event_ref=audit_event_ref,
                        source="admin_cancel" if audit_event_ref else "runtime",
                    )
                    durable_accepted = True

                # A confirmed durable request is not a completed task. If
                # Redis fails after the commit, surface the failure rather
                # than acknowledge a signal that the owner never received.
                snapshot = await self._distributed_store.request_cancel(
                    run_id=run_id,
                    tenant_id=tenant_id,
                )
                snapshot["cancellation_acknowledgement"] = (
                    "durably_accepted" if durable_accepted else "shared_signal_only"
                )
                return snapshot
            except DistributedRunNotFound:
                if durable_accepted:
                    raise
            except DistributedRunTenantMismatch as exc:
                raise RunTenantMismatchError(run_id) from exc
            except DistributedRunNotCancellable as exc:
                raise RunNotCancellableError(str(exc)) from exc
            except DistributedRunStoreUnavailable:
                if durable_accepted:
                    raise

        durable = await self._get_durable(run_id=run_id, tenant_id=tenant_id)
        if durable is not None:
            raise RunNotCancellableError(
                f"Run {run_id} has durable status {durable['status']} but no live cancellable lease"
            )
        raise RunNotFoundError(run_id)

    async def link_audit_event(
        self,
        *,
        run_id: str,
        tenant_id: str,
        audit_event_ref: str,
    ) -> None:
        if not self._settings.durable_run_ledger_enabled:
            return
        try:
            await self._durable_ledger.link_audit_event(
                run_id=run_id,
                tenant_id=tenant_id,
                audit_event_ref=audit_event_ref,
            )
        except DurableRunLedgerUnavailable:
            if self._settings.durable_run_ledger_required:
                raise
            logger.exception(
                "Medusa durable audit linkage unavailable",
                extra={"run_id": run_id, "tenant_id": tenant_id},
            )

    async def get(
        self,
        *,
        run_id: str,
        tenant_id: str,
        require_durable_history: bool = False,
        user_id: str | None = None,
        require_durable_identity: bool = False,
    ) -> dict[str, Any]:
        """Read scoped live/history state; evidence reads require durable identity."""
        require_durable_history = require_durable_history or require_durable_identity
        snapshot: dict[str, Any] | None = None
        async with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                if run.tenant_id != tenant_id:
                    raise RunTenantMismatchError(run_id)
                if user_id is not None and run.user_id != user_id:
                    raise RunNotFoundError(run_id)
        if run is not None:
            await self._recover_local_terminal_view(run)
            await self._retry_local_retention(run)
        async with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                if run.tenant_id != tenant_id:
                    raise RunTenantMismatchError(run_id)
                if user_id is not None and run.user_id != user_id:
                    raise RunNotFoundError(run_id)
                snapshot = run.snapshot()
                snapshot["distributed_control"] = await self._distributed_capability(
                    shared_registered=run.shared_registered,
                    orphaned=run.status is ExecutionRunStatus.ORPHANED,
                )
                if run.status in {
                    ExecutionRunStatus.COMPLETED,
                    ExecutionRunStatus.FAILED,
                    ExecutionRunStatus.CANCELLED,
                } and snapshot["distributed_control"].get("supported"):
                    snapshot["distributed_control"]["lease_alive"] = False
        if snapshot is not None:
            if require_durable_identity:
                await self._verify_live_durable_identity(
                    snapshot, run_id=run_id, tenant_id=tenant_id
                )
            return snapshot

        await self._reconcile_tenant_from_redis(tenant_id)
        if await self._distributed_available():
            try:
                shared = await self._distributed_store.get(
                    run_id=run_id,
                    tenant_id=tenant_id,
                )
            except DistributedRunNotFound:
                pass
            except DistributedRunTenantMismatch as exc:
                raise RunTenantMismatchError(run_id) from exc
            except DistributedRunStoreUnavailable:
                pass
            else:
                if shared.get("tenant_id") != tenant_id:
                    raise RunTenantMismatchError(run_id)
                if user_id is not None and shared.get("user_id") != user_id:
                    raise RunNotFoundError(run_id)
                if (
                    self._settings.durable_run_ledger_enabled
                    and shared.get("terminal_authority") == "durable_arbitrated"
                ):
                    try:
                        durable = await self._get_durable(
                            run_id=run_id, tenant_id=tenant_id
                        )
                    except DurableRunLedgerUnavailable:
                        durable = None
                    if durable is not None:
                        await self._release_terminal_retention(tenant_id, durable)
                if not require_durable_history:
                    return shared
                # Redis owns live coordination, but its snapshot does not
                # carry the original request ID. Join only exact scoped
                # identity evidence from the existing PostgreSQL ledger.
                request_id = await self._verify_live_durable_identity(
                    shared, run_id=run_id, tenant_id=tenant_id
                )
                return {**shared, "request_id": request_id}

        durable = await self._get_durable(
            run_id=run_id,
            tenant_id=tenant_id,
            require_available=require_durable_history,
        )
        if durable is None or (
            user_id is not None and durable.get("user_id") != user_id
        ):
            raise RunNotFoundError(run_id)
        return durable

    async def _verify_live_durable_identity(
        self,
        snapshot: dict[str, Any],
        *,
        run_id: str,
        tenant_id: str,
    ) -> str:
        """Verify the same immutable identity for local and remote live reads."""
        durable = await self._get_durable(
            run_id=run_id, tenant_id=tenant_id, require_available=True
        )
        if (
            durable is None
            or snapshot.get("run_id") != run_id
            or any(
                not isinstance(snapshot.get(key), str)
                or not snapshot[key]
                or snapshot[key] != durable.get(key)
                for key in ("run_id", "tenant_id", "user_id", "correlation_id")
            )
            or not isinstance(durable.get("request_id"), str)
            or not durable["request_id"]
            or (
                "request_id" in snapshot
                and snapshot["request_id"] != durable["request_id"]
            )
        ):
            raise DurableRunLedgerUnavailable("medusa_live_run_identity_unavailable")
        return durable["request_id"]

    async def read_run_transitions(
        self,
        *,
        run_id: str,
        tenant_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        """Read durable history without treating live snapshots as transitions."""
        if not self._settings.durable_run_ledger_enabled:
            raise DurableRunLedgerUnavailable("medusa_durable_ledger_disabled")
        return await self._durable_ledger.read_transitions(
            run_id=run_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool = True,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        await self._reconcile_tenant_from_redis(tenant_id)
        await self._retry_tenant_retention(tenant_id, user_id=user_id)
        async with self._lock:
            uncertain = [
                run
                for run in self._runs.values()
                if run.tenant_id == tenant_id
                and (user_id is None or run.user_id == user_id)
                and run.terminal_unconfirmed
                and not run.terminal_recovered
            ][: self._settings.run_reconciliation_batch_size]
        for run in uncertain:
            await self._recover_local_terminal_view(run)
        async with self._lock:
            local_pairs = [
                (run.snapshot(), run.shared_registered)
                for run in self._runs.values()
                if run.tenant_id == tenant_id
                and (user_id is None or run.user_id == user_id)
                and (
                    include_terminal
                    or run.status
                    in {
                        ExecutionRunStatus.RUNNING,
                        ExecutionRunStatus.CANCELLING,
                        ExecutionRunStatus.ORPHANED,
                    }
                )
            ]

        merged: dict[str, dict[str, Any]] = {}
        for snapshot, shared_registered in local_pairs:
            snapshot["distributed_control"] = await self._distributed_capability(
                shared_registered=shared_registered,
                orphaned=snapshot["status"] == ExecutionRunStatus.ORPHANED.value,
            )
            if snapshot["status"] in {
                "completed",
                "failed",
                "cancelled",
            } and snapshot[
                "distributed_control"
            ].get("supported"):
                snapshot["distributed_control"]["lease_alive"] = False
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
                if (
                    user_id is None or str(snapshot.get("user_id") or "") == user_id
                ) and snapshot["run_id"] not in merged:
                    merged[snapshot["run_id"]] = snapshot

        if self._settings.durable_run_ledger_enabled:
            try:
                durable_rows = await self._durable_ledger.list_runs(
                    tenant_id=tenant_id,
                    include_terminal=include_terminal,
                    **({"user_id": user_id} if user_id is not None else {}),
                )
            except DurableRunLedgerUnavailable:
                if self._settings.durable_run_ledger_required:
                    raise
                durable_rows = []
                logger.exception(
                    "Medusa durable run history unavailable",
                    extra={"tenant_id": tenant_id},
                )
            for snapshot in durable_rows:
                if snapshot["run_id"] not in merged:
                    merged[snapshot["run_id"]] = snapshot

        return sorted(
            merged.values(),
            key=lambda item: item["started_at"] or "",
            reverse=True,
        )

    async def _heartbeat_loop(self, run: ExecutionRun) -> None:
        """Renew Redis ownership and observe remote cancellation requests."""

        try:
            while True:
                await asyncio.sleep(self._settings.run_heartbeat_interval_seconds)
                async with self._lock:
                    if (
                        not run.shared_registered
                        or self._runs.get(run.run_id) is not run
                        or run.task.done()
                        or run.terminal_pending
                        or run.status
                        not in {
                            ExecutionRunStatus.RUNNING,
                            ExecutionRunStatus.CANCELLING,
                        }
                    ):
                        return
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
                except (DistributedRunOwnershipLost, DistributedRunNotFound):
                    await self._record_shared_ownership_loss(run)
                    return
                if not cancel_requested and run.durable_registered:
                    # A remote cancellation may have committed in PostgreSQL
                    # before its Redis signal failed. Only the live Redis
                    # owner may recover that request, and an atomic Redis
                    # request_cancel must recheck ownership before any local
                    # task is interrupted.
                    # Keep PostgreSQL pool waits inside the time remaining
                    # before the next Redis lease renewal. A slow durable
                    # lookup must not turn a healthy owner into an orphan.
                    recovery_read_budget = (
                        self._settings.run_lease_ttl_seconds
                        - self._settings.run_heartbeat_interval_seconds
                    ) / 2
                    try:
                        durable = await asyncio.wait_for(
                            self._durable_ledger.get(
                                run_id=run.run_id,
                                tenant_id=run.tenant_id,
                            ),
                            timeout=recovery_read_budget,
                        )
                    except (DurableRunLedgerUnavailable, asyncio.TimeoutError) as exc:
                        logger.warning(
                            "Medusa durable cancellation recovery read unavailable",
                            extra={
                                "run_id": run.run_id,
                                "tenant_id": run.tenant_id,
                                "error_type": type(exc).__name__,
                            },
                        )
                        continue
                    if (
                        durable is not None
                        and durable.get("status") == "cancellation_requested"
                        and durable.get("tenant_id")
                        == _canonical_tenant_id(run.tenant_id)
                        and durable.get("owner_worker_id") == self._settings.worker_id
                    ):
                        try:
                            await self._distributed_store.request_cancel(
                                run_id=run.run_id,
                                tenant_id=run.tenant_id,
                            )
                        except (
                            DistributedRunStoreUnavailable,
                            DistributedRunNotFound,
                            DistributedRunNotCancellable,
                            DistributedRunTenantMismatch,
                        ) as exc:
                            logger.warning(
                                "Medusa durable cancellation recovery was not accepted by live lease",
                                extra={
                                    "run_id": run.run_id,
                                    "tenant_id": run.tenant_id,
                                    "error_type": type(exc).__name__,
                                },
                            )
                            continue
                        cancel_requested = True
                if cancel_requested:
                    try:
                        admitted = await self._admit_local_cancellation(
                            run, allow_existing=True
                        )
                    except (DurableRunLedgerConflict, DurableRunLedgerUnavailable):
                        continue
                    if not admitted:
                        # A local caller may be admitting the same request.
                        # Keep renewing the lease until it resolves.
                        async with self._lock:
                            if (
                                self._runs.get(run.run_id) is not run
                                or run.status is not ExecutionRunStatus.RUNNING
                            ):
                                return
                        continue
                    await self._signal_local_cancellation(run)
                    # Cancellation is intent, not retirement. Keep the claim
                    # alive while the owned task is still performing cleanup.
                    # The terminal transition owns heartbeat shutdown.
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "Medusa run heartbeat loop failed",
                extra={"run_id": run.run_id, "error_type": type(exc).__name__},
            )

    async def _safe_mark_durable_terminal(
        self,
        *,
        run: ExecutionRun,
        status: ExecutionRunStatus,
        completed_at: datetime,
        error_type: str | None,
        outcome_status: str | None = None,
    ) -> None:
        try:
            await self._durable_ledger.mark_terminal(
                run_id=run.run_id,
                tenant_id=run.tenant_id,
                worker_id=self._settings.worker_id,
                status=status.value,
                completed_at=completed_at,
                error_type=error_type,
                outcome_status=outcome_status,
            )
        except (DurableRunLedgerConflict, DurableRunLedgerUnavailable):
            logger.exception(
                "Medusa durable terminal transition failed",
                extra={"run_id": run.run_id, "status": status.value},
            )
            if self._settings.durable_run_ledger_required:
                raise

    async def _get_durable(
        self,
        *,
        run_id: str,
        tenant_id: str,
        require_available: bool = False,
    ) -> dict[str, Any] | None:
        if not self._settings.durable_run_ledger_enabled:
            if require_available:
                raise DurableRunLedgerUnavailable("medusa_durable_ledger_disabled")
            return None
        try:
            return await self._durable_ledger.get(run_id=run_id, tenant_id=tenant_id)
        except DurableRunLedgerUnavailable:
            if require_available or self._settings.durable_run_ledger_required:
                raise
            logger.exception(
                "Medusa durable run lookup unavailable",
                extra={"run_id": run_id, "tenant_id": tenant_id},
            )
            return None

    def _matches_terminal_identity(
        self, run: ExecutionRun, receipt: dict[str, Any], *, durable: bool
    ) -> bool:
        if any(
            receipt.get(key) != value
            for key, value in (
                ("run_id", run.run_id),
                ("correlation_id", run.correlation_id),
                ("user_id", run.user_id),
                ("owner_worker_id", self._settings.worker_id),
            )
        ):
            return False
        expected_tenant = (
            _canonical_tenant_id(run.tenant_id) if durable else run.tenant_id
        )
        if receipt.get("tenant_id") != expected_tenant:
            return False
        if durable and any(
            receipt.get(key) != value
            for key, value in (
                ("request_id", run.request_id),
                ("session_id", run.session_id),
                ("policy_decision_id", run.policy_decision_id),
            )
        ):
            return False
        return True

    def _matches_terminal_attempt(
        self, run: ExecutionRun, receipt: dict[str, Any], *, durable: bool
    ) -> bool:
        if not self._matches_terminal_identity(run, receipt, durable=durable):
            return False
        valid = {
            "completed": {"success", "partial", "degraded"},
            "failed": {"error", "timeout"},
            "cancelled": {"cancelled"},
            "orphaned": {None},
        }
        try:
            completed = self._parse_time(receipt.get("completed_at"))
            started = self._parse_time(receipt.get("started_at"))
            return (
                completed is not None
                and completed == run.terminal_attempted_at
                and started == run.started_at
                and receipt.get("status") in valid
                and receipt.get("outcome_status") in valid[receipt["status"]]
                and (
                    receipt["status"] != "orphaned"
                    or receipt.get("error_type") == "NativeRetirementUnverified"
                )
            )
        except (TypeError, ValueError):
            return False

    async def _release_terminal_retention(
        self, tenant_id: str, durable: dict[str, Any]
    ) -> bool:
        """Best-effort cleanup; failure cannot erase confirmed durable history."""
        if not self._settings.distributed_run_control_enabled or durable.get(
            "tenant_id"
        ) != _canonical_tenant_id(tenant_id):
            return False
        acknowledge = getattr(
            self._distributed_store, "acknowledge_durable_terminal", None
        )
        if acknowledge is None:
            return False
        try:
            acknowledged = await asyncio.wait_for(
                acknowledge(tenant_id=tenant_id, receipt=durable),
                timeout=self._settings.run_heartbeat_interval_seconds,
            )
        except asyncio.CancelledError:
            record_retention_event("acknowledgement", "cancelled")
            raise
        except (DistributedRunStoreUnavailable, TimeoutError, ValueError) as exc:
            outcome = (
                "timeout"
                if isinstance(exc, TimeoutError)
                else "invalid" if isinstance(exc, ValueError) else "unavailable"
            )
            record_retention_event("acknowledgement", outcome)
            logger.warning(
                "Medusa terminal retention acknowledgement deferred",
                extra={
                    "run_id": durable.get("run_id"),
                    "tenant_id": tenant_id,
                    "retention_outcome": outcome,
                },
            )
            return False
        record_retention_event(
            "acknowledgement",
            "acknowledged" if acknowledged else "not_confirmed",
        )
        return acknowledged

    async def _retry_local_retention(self, run: ExecutionRun) -> None:
        if (
            not run.retention_pending
            or run.terminal_pending
            or not run.durable_registered
            or not run.shared_registered
            or run.completed_at is None
        ):
            return
        receipt = run.snapshot()
        receipt["tenant_id"] = _canonical_tenant_id(run.tenant_id)
        receipt["owner_worker_id"] = self._settings.worker_id
        if await self._release_terminal_retention(run.tenant_id, receipt):
            run.retention_pending = False

    async def _retry_tenant_retention(
        self, tenant_id: str, *, user_id: str | None
    ) -> None:
        """Bound cleanup by both existing batch size and one time budget."""
        if not (
            self._settings.durable_run_ledger_enabled
            and self._settings.distributed_run_control_enabled
        ):
            return
        discover = getattr(self._distributed_store, "pending_terminal_ids", None)
        if discover is None:
            return

        async def repair() -> None:
            seen: set[str] = set()
            for _ in range(self._settings.run_reconciliation_batch_size):
                # Rotate only the item actually attempted. A time-budget
                # interruption must not skip the remainder of a whole batch.
                run_ids = await discover(tenant_id=tenant_id, limit=1)
                if not run_ids:
                    record_retention_event("repair_batch", "empty")
                    return
                if run_ids[0] in seen:
                    record_retention_event("repair_batch", "cycle")
                    return
                run_id = run_ids[0]
                seen.add(run_id)
                durable = await self._get_durable(run_id=run_id, tenant_id=tenant_id)
                if durable is None:
                    record_retention_event("repair_candidate", "durable_missing")
                    continue
                if user_id is not None and durable.get("user_id") != user_id:
                    record_retention_event("repair_candidate", "scope_skipped")
                    continue
                if durable.get("status") not in {
                    "completed",
                    "failed",
                    "cancelled",
                    "orphaned",
                }:
                    record_retention_event("repair_candidate", "not_terminal")
                    continue
                await self._release_terminal_retention(tenant_id, durable)
            record_retention_event("repair_batch", "batch_limit")

        try:
            await asyncio.wait_for(
                repair(), timeout=self._settings.run_heartbeat_interval_seconds
            )
        except asyncio.CancelledError:
            record_retention_event("repair_batch", "cancelled")
            raise
        except (
            DistributedRunStoreUnavailable,
            DurableRunLedgerUnavailable,
            TimeoutError,
        ) as exc:
            outcome = "timeout" if isinstance(exc, TimeoutError) else "unavailable"
            record_retention_event("repair_batch", outcome)
            logger.warning(
                "Medusa terminal retention batch deferred",
                extra={"tenant_id": tenant_id, "retention_outcome": outcome},
            )

    async def _recover_local_terminal_view(self, run: ExecutionRun) -> None:
        """Repair history from exact receipts; never re-authorize a response."""
        if (
            not run.terminal_unconfirmed
            or run.terminal_recovered
            or not run.task.done()
        ):
            return
        scope = {"run_id": run.run_id, "tenant_id": run.tenant_id}
        try:
            receipt = None
            if run.durable_registered:
                receipt = await self._durable_ledger.get(**scope)
            if receipt is None or not self._matches_terminal_attempt(
                run, receipt, durable=True
            ):
                if not run.shared_registered:
                    return
                shared = await self._distributed_store.get(**scope)
                if not self._matches_terminal_attempt(run, shared, durable=False):
                    return
                if run.durable_registered:
                    if (
                        receipt is None
                        or not self._matches_terminal_identity(
                            run, receipt, durable=True
                        )
                        or shared.get("terminal_authority") != "durable_arbitrated"
                    ):
                        return
                    await self._durable_ledger.reconcile_from_shared(
                        **scope,
                        status=shared["status"],
                        reconciled_at=datetime.now(timezone.utc),
                        completed_at=self._parse_time(shared["completed_at"]),
                        error_type=shared.get("error_type"),
                        outcome_status=shared.get("outcome_status"),
                        expected_worker_id=self._settings.worker_id,
                        expected_correlation_id=run.correlation_id,
                        expected_user_id=run.user_id,
                        terminal_authority=shared["terminal_authority"],
                    )
                    receipt = await self._durable_ledger.get(**scope)
                    if receipt is None or not self._matches_terminal_attempt(
                        run, receipt, durable=True
                    ):
                        return
                    if any(
                        receipt.get(key) != shared.get(key)
                        for key in ("status", "outcome_status", "error_type")
                    ):
                        return
                else:
                    receipt = shared
            completed_at = self._parse_time(receipt["completed_at"])
            assert completed_at is not None
            if run.durable_registered and run.shared_registered:
                acknowledged = await self._release_terminal_retention(
                    run.tenant_id, receipt
                )
                run.retention_pending = not acknowledged
        except (
            DistributedRunNotFound,
            DistributedRunTenantMismatch,
            DistributedRunStoreUnavailable,
            DurableRunLedgerUnavailable,
            DurableRunLedgerConflict,
            ValueError,
        ):
            return
        async with self._lock:
            if (
                self._runs.get(run.run_id) is not run
                or not run.terminal_unconfirmed
                or run.terminal_recovered
            ):
                return
            run.terminal_recovered = True
            self._publish_terminal_locked(
                run,
                ExecutionRunStatus(receipt["status"]),
                completed_at,
                receipt.get("error_type"),
                receipt.get("outcome_status"),
            )
        logger.info(
            "Medusa recovered verified terminal history",
            extra={"run_id": run.run_id, "tenant_id": run.tenant_id},
        )

    async def _reconcile_tenant_from_redis(self, tenant_id: str) -> None:
        """Boundedly repair durable active rows using Redis live authority only."""

        if not self._settings.durable_run_ledger_enabled:
            return
        if not await self._distributed_available():
            return
        list_reconcilable = getattr(self._durable_ledger, "list_reconcilable", None)
        reconcile = getattr(self._durable_ledger, "reconcile_from_shared", None)
        if list_reconcilable is None or reconcile is None:
            return
        try:
            rows = await list_reconcilable(
                tenant_id=tenant_id,
                limit=self._settings.run_reconciliation_batch_size,
            )
        except DurableRunLedgerUnavailable:
            if self._settings.durable_run_ledger_required:
                raise
            logger.exception(
                "Medusa reconciliation durable read unavailable",
                extra={"tenant_id": tenant_id},
            )
            return

        async with self._lock:
            local_run_ids = {
                run_id
                for run_id, run in self._runs.items()
                if run.tenant_id == tenant_id
                and not run.shared_ownership_lost
                and (not run.terminal_unconfirmed or not run.shared_registered)
            }

        reconciled = 0
        for row in rows:
            run_id = str(row["run_id"])
            if run_id in local_run_ids:
                continue
            try:
                observe = getattr(self._distributed_store, "observe_reconciliation", None)
                if observe is None:
                    # Older injected adapters can supply receipts, but cannot
                    # prove lease expiry from a collapsed orphan snapshot.
                    shared = await self._distributed_store.get(
                        run_id=run_id, tenant_id=tenant_id
                    )
                    if shared.get("status") == "orphaned":
                        continue
                else:
                    evidence = await observe(run_id=run_id, tenant_id=tenant_id)
                    if evidence.snapshot is None:
                        await self._record_unresolved_shared_evidence(
                            row, tenant_id, evidence.kind
                        )
                        continue
                    shared = evidence.snapshot
                    if evidence.kind == "active" and shared.get("status") == "orphaned":
                        # Clock advancement between observations is not a new proof.
                        continue
                    if evidence.kind == "lease_expired" and (
                        evidence.expiry_fence is None
                        or shared.get("status") != "orphaned"
                        or any(shared.get(key) for key in (
                            "completed_at", "outcome_status", "terminal_authority",
                        ))
                    ):
                        # Expiry evidence must never impersonate a terminal receipt.
                        continue
            except DistributedRunStoreUnavailable:
                return
            except DistributedRunTenantMismatch:
                logger.error(
                    "Medusa reconciliation tenant mismatch",
                    extra={"run_id": run_id, "tenant_id": tenant_id},
                )
                continue
            except DistributedRunNotFound:
                await self._record_unresolved_shared_evidence(row, tenant_id, "absent")
                continue

            # Only a present identity-matched shared receipt can repair history.
            if any(
                not shared.get(key) or shared.get(key) != row.get(key)
                for key in ("run_id", "correlation_id", "user_id", "owner_worker_id")
            ):
                logger.warning(
                    "Medusa reconciliation identity mismatch",
                    extra={"run_id": run_id, "tenant_id": tenant_id},
                )
                continue
            if not shared.get("tenant_id") or _canonical_tenant_id(
                str(shared["tenant_id"])
            ) != _canonical_tenant_id(tenant_id):
                continue
            shared_status = str(shared.get("status") or "")
            if shared_status == "running":
                continue
            if shared_status not in {
                "cancelling",
                "orphaned",
                "completed",
                "failed",
                "cancelled",
            }:
                logger.warning(
                    "Medusa reconciliation ignored unknown shared status",
                    extra={"run_id": run_id, "status": shared_status},
                )
                continue
            if shared_status in {"completed", "failed", "cancelled"} and (
                not shared.get("completed_at") or not shared.get("owner_worker_id")
            ):
                continue
            try:
                expiry_fence: dict[str, Any] = {}
                if shared_status == "orphaned" and not shared.get("completed_at"):
                    # Only the classified adapter can distinguish expiry
                    # from a missing claim or a missing hash.
                    if observe is None or evidence.kind != "lease_expired":
                        continue
                    heartbeat = self._parse_time(row.get("heartbeat_at"))
                    if (
                        row.get("status") not in {"running", "cancellation_requested"}
                        or heartbeat is None
                        or (datetime.now(timezone.utc) - heartbeat).total_seconds()
                        < self._settings.run_orphan_grace_seconds
                    ):
                        continue
                    read = getattr(self._durable_ledger, "read_admission_provenance", None)
                    if read is None:
                        continue
                    provenance = await read(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        user_id=str(row.get("user_id") or ""),
                        correlation_id=str(row.get("correlation_id") or ""),
                        worker_id=str(row.get("owner_worker_id") or ""),
                    )
                    if (
                        provenance is None
                        or provenance.phase != "running"
                        or provenance.shared_registration != "acknowledged"
                    ):
                        continue

                    async def confirm_expiry() -> bool:
                        try:
                            current = await asyncio.wait_for(
                                observe(run_id=run_id, tenant_id=tenant_id),
                                timeout=self._settings.run_heartbeat_interval_seconds,
                            )
                        except (
                            DistributedRunStoreUnavailable,
                            DistributedRunTenantMismatch,
                            TimeoutError,
                            ValueError,
                        ):
                            return False
                        return (
                            current.kind == "lease_expired"
                            and current.expiry_fence == evidence.expiry_fence
                            and current.snapshot == shared
                        )

                    expiry_fence = {
                        "expected_status": row["status"],
                        "expected_heartbeat_at": heartbeat,
                        "confirm_expiry": confirm_expiry,
                    }
                changed = await reconcile(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    status=shared_status,
                    reconciled_at=datetime.now(timezone.utc),
                    completed_at=self._parse_time(shared.get("completed_at")),
                    error_type=shared.get("error_type"),
                    outcome_status=shared.get("outcome_status"),
                    expected_worker_id=shared.get("owner_worker_id"),
                    expected_correlation_id=shared.get("correlation_id"),
                    expected_user_id=shared.get("user_id"),
                    terminal_authority=shared.get("terminal_authority"),
                    **expiry_fence,
                )
            except ValueError:
                logger.warning(
                    "Medusa reconciliation ignored invalid receipt",
                    extra={"run_id": run_id, "tenant_id": tenant_id},
                )
                continue
            except DurableRunLedgerUnavailable:
                if self._settings.durable_run_ledger_required:
                    raise
                logger.exception(
                    "Medusa reconciliation durable write unavailable",
                    extra={"run_id": run_id, "tenant_id": tenant_id},
                )
                return
            if changed:
                reconciled += 1
            if shared.get("terminal_authority") == "durable_arbitrated":
                durable = await self._get_durable(run_id=run_id, tenant_id=tenant_id)
                if durable is not None:
                    await self._release_terminal_retention(tenant_id, durable)

        if reconciled:
            logger.info(
                "Medusa reconciled durable history from Redis",
                extra={"tenant_id": tenant_id, "reconciled_run_count": reconciled},
            )

    async def _record_unresolved_shared_evidence(
        self, row: dict[str, Any], tenant_id: str, reason: str
    ) -> None:
        """Observe admission history without granting repair or execution."""
        provenance_status = "unobserved"
        read = getattr(self._durable_ledger, "read_admission_provenance", None)
        if read is not None:
            try:
                evidence = await read(
                    run_id=str(row["run_id"]),
                    tenant_id=tenant_id,
                    user_id=str(row.get("user_id") or ""),
                    correlation_id=str(row.get("correlation_id") or ""),
                    worker_id=str(row.get("owner_worker_id") or ""),
                )
                provenance_status = evidence.phase if evidence is not None else "absent"
            except (DurableRunLedgerUnavailable, ValueError):
                provenance_status = "unavailable"
        logger.warning(
            "medusa_shared_evidence_unresolved",
            extra={
                "run_id": row["run_id"],
                "tenant_id": tenant_id,
                "correlation_id": row.get("correlation_id"),
                "reason_code": reason,
                "admission_phase": provenance_status,
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
        orphaned: bool = False,
    ) -> dict[str, Any]:
        if orphaned:
            return {"supported": False, "reason_code": "run_owner_unresolved"}
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
            return {"supported": False, "reason_code": "shared_redis_unavailable"}
        return {"supported": True, "lease_alive": True}

    def _parse_time(self, value: Any) -> datetime | None:
        if not value:
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
