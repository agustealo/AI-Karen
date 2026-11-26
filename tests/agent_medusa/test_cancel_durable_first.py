"""Fail-closed ordering of local Medusa cancellation and durable truth."""

from __future__ import annotations

import asyncio

import pytest

from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
    DurableRunLedgerConflict,
    DurableRunLedgerUnavailable,
)
from ai_karen_engine.agent_medusa.execution.run_manager import (
    ExecutionRunStatus,
    MedusaRunManager,
)
from ai_karen_engine.config.agent_medusa import AgentMedusaRuntimeSettings


class _RecordingSharedControl:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def request_cancel(self, *, run_id: str, tenant_id: str) -> None:
        self.events.append("redis_cancel")


class _RecordingDurableControl:
    def __init__(self, events: list[str], failure: str) -> None:
        self.events = events
        self.failure = failure

    async def mark_cancelling(
        self,
        *,
        run_id: str,
        tenant_id: str,
        requested_at: object,
        audit_event_ref: str | None,
        source: str,
    ) -> None:
        self.events.append("durable_cancel")
        if self.failure == "unavailable":
            raise DurableRunLedgerUnavailable("injected durable outage")
        if self.failure == "conflict":
            raise DurableRunLedgerConflict("injected stale durable state")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unavailable", "conflict", "none"])
async def test_local_cancel_never_signals_redis_before_required_durable_transition(
    failure: str,
) -> None:
    events: list[str] = []
    manager = MedusaRunManager(
        settings=AgentMedusaRuntimeSettings(
            distributed_run_control_enabled=False,
            durable_run_ledger_enabled=False,
            durable_run_ledger_required=False,
            worker_id="test-worker",
        )
    )
    started = asyncio.Event()

    async def work() -> None:
        started.set()
        await asyncio.sleep(60)

    task = asyncio.create_task(work())
    try:
        await started.wait()
        run = await manager.register(
            run_id="run-order",
            correlation_id="corr-order",
            tenant_id="tenant-a",
            user_id="owner-a",
            task=task,
        )
        # Force the combined registered-store branch without external DB/Redis.
        # These injected test doubles are not used by production.
        run.shared_registered = True
        run.durable_registered = True
        manager._distributed_store = _RecordingSharedControl(events)
        manager._durable_ledger = _RecordingDurableControl(events, failure)
        manager._settings = AgentMedusaRuntimeSettings(
            distributed_run_control_enabled=False,
            durable_run_ledger_enabled=True,
            durable_run_ledger_required=True,
            worker_id="test-worker",
        )

        if failure != "none":
            exception = (
                DurableRunLedgerUnavailable
                if failure == "unavailable"
                else DurableRunLedgerConflict
            )
            with pytest.raises(exception):
                await manager.cancel(
                    run_id="run-order",
                    tenant_id="tenant-a",
                    audit_event_ref="audit-order",
                )
            assert events == ["durable_cancel"]
            assert run.status is ExecutionRunStatus.RUNNING
            assert not task.done()
        else:
            # Avoid querying shared capability after cancellation by making the
            # recording control explicitly describe its local-only state.
            async def available() -> bool:
                return False

            manager._distributed_store.available = available
            result = await manager.cancel(
                run_id="run-order",
                tenant_id="tenant-a",
                audit_event_ref="audit-order",
            )
            assert result["status"] == "cancelling"
            assert events == ["durable_cancel", "redis_cancel"]
            assert task.cancelling() > 0
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unavailable", "conflict"])
@pytest.mark.parametrize("terminal", ["orphaned", "cancelled"])
async def test_failed_cancel_admission_cannot_reopen_concurrent_terminal_run(
    failure: str, terminal: str
) -> None:
    """A failed late durable response cannot undo an independently closed run."""
    manager = MedusaRunManager(
        settings=AgentMedusaRuntimeSettings(
            distributed_run_control_enabled=False,
            durable_run_ledger_enabled=False,
            durable_run_ledger_required=False,
            worker_id="test-worker",
        )
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    terminal_writes: list[dict[str, object]] = []

    class BlockingLedger(_RecordingDurableControl):
        async def mark_cancelling(self, **kwargs: object) -> None:
            entered.set()
            await release.wait()
            if failure == "unavailable":
                raise DurableRunLedgerUnavailable("test-only late outage")
            raise DurableRunLedgerConflict("test-only late conflict")

        async def mark_terminal(self, **kwargs: object) -> None:
            terminal_writes.append(kwargs)

    task = asyncio.create_task(asyncio.sleep(60))
    cancellation: asyncio.Task | None = None
    try:
        run = await manager.register(
            run_id="run-race",
            correlation_id="corr-race",
            tenant_id="tenant-a",
            user_id="owner-a",
            task=task,
        )
        run.durable_registered = True
        manager._durable_ledger = BlockingLedger([], failure)
        manager._settings = AgentMedusaRuntimeSettings(
            distributed_run_control_enabled=False,
            durable_run_ledger_enabled=True,
            durable_run_ledger_required=True,
            worker_id="test-worker",
        )
        cancellation = asyncio.create_task(
            manager.cancel(
                run_id=run.run_id,
                tenant_id=run.tenant_id,
                audit_event_ref="audit-race",
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert run.status is ExecutionRunStatus.CANCELLING

        if terminal == "orphaned":
            await manager.mark_retirement_unverified(run.run_id)
        else:
            await manager.mark_cancelled(run.run_id)
        snapshot = await manager.get(run_id=run.run_id, tenant_id=run.tenant_id)
        assert snapshot["status"] == terminal
        assert snapshot["completed_at"] is not None
        assert snapshot["cancellable"] is False
        assert len(terminal_writes) == 1
        assert terminal_writes[0]["status"] == terminal

        release.set()
        error = (
            DurableRunLedgerUnavailable
            if failure == "unavailable"
            else DurableRunLedgerConflict
        )
        with pytest.raises(error):
            await asyncio.wait_for(cancellation, timeout=5)

        assert await manager.get(
            run_id=run.run_id, tenant_id=run.tenant_id
        ) == snapshot
        assert task.cancelling() == 0
        assert len(terminal_writes) == 1
    finally:
        release.set()
        if cancellation is not None:
            if not cancellation.done():
                cancellation.cancel()
            await asyncio.gather(cancellation, return_exceptions=True)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
