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
