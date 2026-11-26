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
@pytest.mark.parametrize("cancel_requested", [False, True])
async def test_unverified_retirement_never_claims_cancellation_or_success(
    cancel_requested,
):
    from ai_karen_engine.agent_medusa.execution.run_manager import (
        RunNotCancellableError,
    )

    manager = MedusaRunManager(settings=_local_settings())
    task = asyncio.create_task(asyncio.sleep(60))
    scope = dict(run_id="unresolved", tenant_id="tenant-a")
    try:
        await manager.register(
            **scope, correlation_id="corr", user_id="owner", task=task
        )
        if cancel_requested:
            await manager.cancel(**scope)
        await manager.mark_retirement_unverified("unresolved")
        await manager.mark_cancelled("unresolved")
        assert (
            await manager.mark_response("unresolved", "success")
            is ExecutionRunStatus.ORPHANED
        )
        snapshot = await manager.get(**scope)
        assert snapshot["status"] == "orphaned"
        assert snapshot["error_type"] == "NativeRetirementUnverified"
        assert snapshot["outcome_status"] is None
        assert snapshot["cancellable"] is False
        assert snapshot["distributed_control"]["supported"] is False
        active = await manager.list_runs(tenant_id="tenant-a", include_terminal=False)
        assert [row["run_id"] for row in active] == ["unresolved"]
        with pytest.raises(RunNotCancellableError):
            await manager.cancel(**scope)
        with pytest.raises(RuntimeError, match="already active or unresolved"):
            await manager.register(
                **scope, correlation_id="corr", user_id="owner", task=task
            )
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "match",
        "foreign_owner",
        "foreign_tenant",
        "missing",
        "outage",
        "disabled",
        "wrong_run",
        "wrong_owner",
        "wrong_tenant",
        "wrong_correlation",
        "missing_request",
        "conflicting_request",
    ],
)
async def test_strict_remote_history_requires_exact_durable_identity(mode):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
        DurableRunLedgerUnavailable,
    )
    from ai_karen_engine.agent_medusa.execution.run_manager import RunNotFoundError

    shared = {
        "run_id": "run",
        "tenant_id": "tenant-a",
        "user_id": "owner",
        "correlation_id": "corr",
        "status": "running",
        "cancellable": True,
    }
    record = {
        **shared,
        "request_id": "original-request",
        "status": "completed",
        "cancellable": False,
    }
    if mode == "foreign_owner":
        shared["user_id"] = "foreign"
    elif mode == "foreign_tenant":
        shared["tenant_id"] = "foreign"
    elif mode == "wrong_run":
        record["run_id"] = "different"
    elif mode == "wrong_owner":
        record["user_id"] = "different"
    elif mode == "wrong_tenant":
        record["tenant_id"] = "different"
    elif mode == "wrong_correlation":
        record["correlation_id"] = "different"
    elif mode == "missing_request":
        record["request_id"] = ""
    elif mode == "conflicting_request":
        shared["request_id"] = "different"

    ledger = SimpleNamespace(
        get=AsyncMock(return_value=None if mode == "missing" else record)
    )
    if mode == "outage":
        ledger.get.side_effect = DurableRunLedgerUnavailable("private failure")
    store = SimpleNamespace(
        available=AsyncMock(return_value=True),
        get=AsyncMock(return_value=shared),
    )
    settings = AgentMedusaRuntimeSettings(
        distributed_run_control_enabled=True,
        durable_run_ledger_enabled=mode != "disabled",
        durable_run_ledger_required=mode != "disabled",
        worker_id="observer",
    )
    manager = MedusaRunManager(
        settings=settings, distributed_store=store, durable_ledger=ledger
    )
    scope = dict(run_id="run", tenant_id="tenant-a", user_id="owner")
    if mode == "match":
        result = await manager.get(**scope, require_durable_history=True)
        assert result == {**shared, "request_id": "original-request"}
        assert result["status"] == "running"
        assert result["cancellable"] is True
        assert "request_id" not in shared
        assert await manager.get(**scope) == shared
    else:
        expected = {
            "foreign_owner": RunNotFoundError,
            "foreign_tenant": RunTenantMismatchError,
        }.get(mode, DurableRunLedgerUnavailable)
        with pytest.raises(expected):
            await manager.get(**scope, require_durable_history=True)
    if mode in {"foreign_owner", "foreign_tenant", "disabled"}:
        ledger.get.assert_not_awaited()
    else:
        ledger.get.assert_awaited_once_with(run_id="run", tenant_id="tenant-a")
