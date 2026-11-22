"""Live SQLAlchemy session lifecycle proof for stalled PostgreSQL rollback.

This test deliberately holds a real SQLAlchemy session rollback inside its
state transition. A mocked session cannot detect IllegalStateChangeError or
verify connection-pool recovery.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import event, text
from sqlalchemy.util.concurrency import await_only

from ai_karen_engine.persistence.postgres.engine import get_postgres_engine
from ai_karen_engine.persistence.postgres.transactions import (
    rollback_async_transaction,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1",
        reason="requires isolated real PostgreSQL and SQLAlchemy AsyncSession",
    ),
]


@pytest.mark.timeout(30)
async def test_live_sqlalchemy_rollback_cannot_race_invalidation_or_leak_pool():
    """A held SQLAlchemy rollback must not be invalidated concurrently."""
    engine = get_postgres_engine()
    baseline = engine.async_engine.pool.checkedout()
    settings = SimpleNamespace(pool=SimpleNamespace(
        rollback_timeout_seconds=0.1,
        invalidate_timeout_seconds=0.1,
    ))
    entered_rollback = asyncio.Event()
    release_rollback = asyncio.Event()
    rollback_task = None
    invalidation_attempts = 0
    session = engine.async_session_factory()

    def hold_real_rollback(sync_session, previous_transaction):
        # Called from SQLAlchemy's actual rollback transition, in its
        # greenlet. await_only suspends without blocking the event loop.
        entered_rollback.set()
        try:
            await_only(release_rollback.wait())
        except asyncio.CancelledError:
            # Simulate an uncooperative transport until explicitly released.
            await_only(release_rollback.wait())

    try:
        await session.execute(text("SELECT 1"))
        event.listen(session.sync_session, "after_soft_rollback", hold_real_rollback)
        with patch(
            "ai_karen_engine.persistence.postgres.transactions.get_database_settings",
            return_value=settings,
        ), patch.object(
            session, "invalidate", wraps=session.invalidate,
        ) as invalidate_spy:
            rollback_task = asyncio.create_task(rollback_async_transaction(session))
            await asyncio.wait_for(entered_rollback.wait(), timeout=5)
            # Explicitly assert no session-state transition is attempted
            # while the real SQLAlchemy rollback remains suspended.
            try:
                await asyncio.wait_for(asyncio.shield(rollback_task), timeout=5)
            except (RuntimeError, TimeoutError):
                assert rollback_task.done(), "rollback cleanup failed to terminate"
            # Record the observed invalidation attempt, but always finish
            # controlled teardown and collect pool recovery evidence before
            # raising the transaction-safety assertion.
            invalidation_attempts = invalidate_spy.await_count
    finally:
        release_rollback.set()
        if rollback_task is not None:
            try:
                await asyncio.wait_for(rollback_task, timeout=5)
            except BaseException:
                pass
        event.remove(session.sync_session, "after_soft_rollback", hold_real_rollback)
        await asyncio.wait_for(session.close(), timeout=5)

    recovered_checkout_count = engine.async_engine.pool.checkedout()
    async with engine.async_session_factory() as healthy:
        assert (await healthy.execute(text("SELECT 1"))).scalar_one() == 1
    final_checkout_count = engine.async_engine.pool.checkedout()
    assert recovered_checkout_count == baseline, (
        "PostgreSQL pool still has checked-out connections after teardown: "
        f"before={baseline}, after={recovered_checkout_count}"
    )
    assert final_checkout_count == baseline, (
        "Fresh SQLAlchemy query did not restore pool checkout baseline"
    )
    assert invalidation_attempts == 0, (
        "session.invalidate raced an active SQLAlchemy rollback: "
        f"attempts={invalidation_attempts}"
    )
