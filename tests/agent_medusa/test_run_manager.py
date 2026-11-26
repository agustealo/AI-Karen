from __future__ import annotations

import asyncio

import pytest

from ai_karen_engine.agent_medusa.execution.run_manager import (
    ExecutionRunStatus,
    MedusaRunManager,
    RunTenantMismatchError,
)
from ai_karen_engine.config.agent_medusa import AgentMedusaRuntimeSettings


def _local_settings() -> AgentMedusaRuntimeSettings:
    return AgentMedusaRuntimeSettings(
        distributed_run_control_enabled=False,
        durable_run_ledger_enabled=False,
        durable_run_ledger_required=False,
        worker_id="test-local-worker",
    )


def test_run_manager_cancels_actual_task_and_records_terminal_state() -> None:
    async def scenario() -> None:
        manager = MedusaRunManager(settings=_local_settings())
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def worker() -> None:
            started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(worker())
        await started.wait()
        await manager.register(
            run_id="run-1",
            correlation_id="corr-1",
            tenant_id="tenant-a",
            user_id="user-a",
            task=task,
        )

        cancelling = await manager.cancel(run_id="run-1", tenant_id="tenant-a")
        assert cancelling["status"] == ExecutionRunStatus.CANCELLING.value
        assert cancelling["cancellable"] is False

        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()

        await manager.mark_cancelled("run-1")
        terminal = await manager.get(run_id="run-1", tenant_id="tenant-a")
        assert terminal["status"] == ExecutionRunStatus.CANCELLED.value
        assert terminal["completed_at"] is not None
        assert terminal["cancellable"] is False

    asyncio.run(scenario())


def test_run_manager_blocks_cross_tenant_observation_and_cancellation() -> None:
    async def scenario() -> None:
        manager = MedusaRunManager(settings=_local_settings())
        task = asyncio.create_task(asyncio.sleep(60))
        await manager.register(
            run_id="run-2",
            correlation_id="corr-2",
            tenant_id="tenant-a",
            user_id="user-a",
            task=task,
        )

        with pytest.raises(RunTenantMismatchError):
            await manager.get(run_id="run-2", tenant_id="tenant-b")
        with pytest.raises(RunTenantMismatchError):
            await manager.cancel(run_id="run-2", tenant_id="tenant-b")

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["disabled", "outage", "absent", "recorded"])
async def test_strict_history_lookup_distinguishes_unavailable_from_absent(mode):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
        DurableRunLedgerUnavailable,
    )
    from ai_karen_engine.agent_medusa.execution.run_manager import RunNotFoundError

    record = {"run_id": "run", "tenant_id": "tenant-a", "user_id": "owner"}
    ledger = SimpleNamespace(
        get=AsyncMock(return_value=record if mode == "recorded" else None)
    )
    if mode == "outage":
        ledger.get.side_effect = DurableRunLedgerUnavailable("private failure")
    settings = AgentMedusaRuntimeSettings(
        distributed_run_control_enabled=False,
        durable_run_ledger_enabled=mode != "disabled",
        durable_run_ledger_required=mode != "disabled",
        worker_id="test-local-worker",
    )
    manager = MedusaRunManager(settings=settings, durable_ledger=ledger)
    scope = dict(run_id="run", tenant_id="tenant-a", require_durable_history=True)
    if mode == "recorded":
        assert await manager.get(**scope) == record
    else:
        expected = RunNotFoundError if mode == "absent" else DurableRunLedgerUnavailable
        with pytest.raises(expected):
            await manager.get(**scope)
    if mode == "disabled":
        ledger.get.assert_not_awaited()
        # Preserve the existing non-strict read contract.
        with pytest.raises(RunNotFoundError):
            await manager.get(run_id="run", tenant_id="tenant-a")
    else:
        ledger.get.assert_awaited_once_with(run_id="run", tenant_id="tenant-a")


@pytest.mark.asyncio
async def test_strict_history_lookup_can_use_live_owner_without_durable_ledger():
    manager = MedusaRunManager(settings=_local_settings())
    task = asyncio.create_task(asyncio.sleep(60))
    try:
        await manager.register(
            run_id="live",
            correlation_id="corr",
            tenant_id="tenant-a",
            user_id="owner",
            task=task,
        )
        record = await manager.get(
            run_id="live", tenant_id="tenant-a", require_durable_history=True
        )
        assert record["user_id"] == "owner"
        with pytest.raises(RunTenantMismatchError):
            await manager.get(
                run_id="live", tenant_id="tenant-b", require_durable_history=True
            )
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
