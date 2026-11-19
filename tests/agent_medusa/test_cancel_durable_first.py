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
