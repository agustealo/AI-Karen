"""Cancellation-regression tests for NeuroVault's caller-owned rollback boundary."""

import asyncio

import pytest

from ai_karen_engine.platform.memory.postgres.vault import PostgresNeuroVault


@pytest.mark.asyncio
async def test_rollback_waits_for_completion_after_repeated_cancellation():
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    class Transaction:
        async def rollback(self):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()

    worker = asyncio.create_task(
        PostgresNeuroVault._rollback_caller_transaction(Transaction())
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    worker.cancel()
    await asyncio.sleep(0)
    worker.cancel()
    await asyncio.sleep(0)
    assert not worker.done(), "rollback must not detach from a cancelled caller"
    release.set()
    await asyncio.wait_for(worker, timeout=2)
    assert calls == 1


@pytest.mark.asyncio
async def test_rollback_failure_is_not_reported_as_success():
    class Transaction:
        async def rollback(self):
            raise RuntimeError("database rollback failed")

    with pytest.raises(RuntimeError, match="database rollback failed"):
        await PostgresNeuroVault._rollback_caller_transaction(Transaction())
