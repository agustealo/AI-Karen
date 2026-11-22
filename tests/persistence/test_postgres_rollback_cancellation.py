"""Canonical PostgreSQL rollback cancellation and stalled-driver regression contracts."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_karen_engine.persistence.postgres.transactions import (
    rollback_async_transaction,
)

@pytest.fixture(autouse=True)
def fast_cleanup_deadlines():
    """Exercise the canonical deadlines without waiting for production limits."""
    settings = SimpleNamespace(pool=SimpleNamespace(
        rollback_timeout_seconds=0.1,
        invalidate_timeout_seconds=0.1,
    ))
    with patch(
        "ai_karen_engine.persistence.postgres.transactions.get_database_settings",
        return_value=settings,
    ):
        yield



@pytest.mark.asyncio
async def test_rollback_success_finishes_before_return():
    session = MagicMock()
    session.rollback = AsyncMock(return_value=None)
    session.invalidate = AsyncMock()
    await rollback_async_transaction(session)
    session.rollback.assert_awaited_once()
    session.invalidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_rollback_failure_invalidates_and_propagates():
    session = MagicMock()
    session.rollback = AsyncMock(side_effect=RuntimeError("rollback failed"))
    session.invalidate = AsyncMock(return_value=None)
    with pytest.raises(RuntimeError, match="rollback failed"):
        await rollback_async_transaction(session)
    session.invalidate.assert_awaited_once()


@pytest.mark.asyncio
async def test_stalled_rollback_must_terminate_without_leaking_rollback_task():
    """Intentionally fail on unbounded cleanup; release event for CI hygiene."""
    gate = asyncio.Event()
    started = asyncio.Event()
    finished = asyncio.Event()
    session = MagicMock()

    async def stalled_rollback():
        started.set()
        try:
            await gate.wait()
        finally:
            finished.set()

    session.rollback = AsyncMock(side_effect=stalled_rollback)
    session.invalidate = AsyncMock(return_value=None)

    task = asyncio.create_task(rollback_async_transaction(session))
    try:
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        # A robust rollback owner must stop waiting when its finite cleanup
        # deadline expires and must never claim the rollback succeeded.
        # Current code is intentionally known to violate this contract.
        with pytest.raises((TimeoutError, RuntimeError, asyncio.CancelledError)):
            await asyncio.wait_for(asyncio.shield(task), timeout=2)
        assert task.done(), "stalled rollback retained a child task"
    finally:
        gate.set()
        try:
            await asyncio.wait_for(task, timeout=2)
        except (TimeoutError, RuntimeError, asyncio.CancelledError):
            pass


@pytest.mark.asyncio
async def test_stalled_invalidation_is_not_an_unbounded_cleanup_loop():
    gate = asyncio.Event()
    started = asyncio.Event()
    session = MagicMock()
    session.rollback = AsyncMock(side_effect=RuntimeError("rollback failed"))

    async def stalled_invalidate():
        started.set()
        await gate.wait()

    session.invalidate = AsyncMock(side_effect=stalled_invalidate)
    task = asyncio.create_task(rollback_async_transaction(session))
    try:
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises((TimeoutError, RuntimeError, asyncio.CancelledError)):
            await asyncio.wait_for(asyncio.shield(task), timeout=2)
        assert task.done(), "stalled invalidation retained a child task"
    finally:
        gate.set()
        try:
            await asyncio.wait_for(task, timeout=2)
        except RuntimeError:
            pass
