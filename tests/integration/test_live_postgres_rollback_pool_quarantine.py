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
    # The canonical engine pools asyncpg connections across these tests;
    # running each test on a new loop would reuse a driver from a closed loop.
    pytest.mark.asyncio(loop_scope="module"),
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

    def hold_real_rollback(connection):
        # Only suspend the target connection. Independent queries must be
        # able to roll back normally while this rollback is held.
        if connection.connection.driver_connection is not held_driver:
            return
        # The event fires before DBAPI rollback/transaction closure.
        entered_rollback.set()
        try:
            await_only(release_rollback.wait())
        except asyncio.CancelledError:
            # Simulate an uncooperative transport until explicitly released.
            await_only(release_rollback.wait())

    try:
        await session.execute(text("SELECT 1"))
        assert engine.async_engine.pool.checkedout() == baseline + 1
        # The pool-owned connection must be detached before the rollback
        # starts. Capture its driver identity before SQLAlchemy enters the
        # rollback state machine, when introspection is still permitted.
        held_driver = session.sync_session.connection().connection.driver_connection
        event.listen(engine.async_engine.sync_engine, "rollback", hold_real_rollback)
        with patch(
            "ai_karen_engine.persistence.postgres.transactions.get_database_settings",
            return_value=settings,
        ), patch.object(
            session, "invalidate", wraps=session.invalidate,
        ) as invalidate_spy:
            rollback_task = asyncio.create_task(rollback_async_transaction(session))
            await asyncio.wait_for(entered_rollback.wait(), timeout=5)
            # The connection is intentionally still checked out during the
            # bounded rollback attempt. Quarantine is required only after
            # that attempt has expired and the caller receives uncertainty.
            assert engine.async_engine.pool.checkedout() == baseline + 1
            with pytest.raises(
                RuntimeError, match="connection_uncertain"
            ) as uncertain:
                await asyncio.wait_for(asyncio.shield(rollback_task), timeout=5)
            assert getattr(uncertain.value, "retirement_task", None) is not None
            assert engine.async_engine.pool.checkedout() == baseline, (
                "the uncertain rollback still owns a reusable pooled connection"
            )
            # A fresh scoped connection must be distinct from the held,
            # detached driver while rollback is still suspended.
            async with engine.async_session_factory() as other:
                other_connection = await other.connection()
                assert (
                    other_connection.sync_connection.connection.driver_connection
                    is not held_driver
                ), "the held rollback connection was reused by the pool"
                assert (await other.execute(text("SELECT 1"))).scalar_one() == 1
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
        retirement_task = None
        if rollback_task is not None:
            try:
                await asyncio.wait_for(rollback_task, timeout=5)
            except BaseException as exc:
                retirement_task = getattr(exc, "retirement_task", None)
        event.remove(engine.async_engine.sync_engine, "rollback", hold_real_rollback)
        if retirement_task is not None:
            # The original rollback task owns session retirement. Never
            # introduce an independent concurrent close in this test.
            await asyncio.wait_for(retirement_task, timeout=5)
        else:
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


@pytest.mark.timeout(30)
async def test_ordinary_rollback_preserves_healthy_pool_connection():
    """A successful rollback must not discard a healthy connection every time."""
    engine = get_postgres_engine()
    baseline = engine.async_engine.pool.checkedout()
    session = engine.async_session_factory()
    try:
        await session.execute(text("SELECT 1"))
        original_driver = (
            (await session.connection()).sync_connection.connection.driver_connection
        )
        await rollback_async_transaction(session)
        assert engine.async_engine.pool.checkedout() == baseline
        # A successful rollback is not an uncertain driver state. The same
        # healthy connection should remain available to the pool.
        async with engine.async_session_factory() as another:
            connection = await another.connection()
            assert (
                connection.sync_connection.connection.driver_connection
                is original_driver
            ), "ordinary rollback discarded a healthy pooled connection"
            assert (await another.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        await session.close()
    assert engine.async_engine.pool.checkedout() == baseline


@pytest.mark.timeout(30)
async def test_already_invalidated_live_connection_still_allows_rollback():
    """Connection loss during a live transaction must not block rollback."""
    from sqlalchemy.exc import PendingRollbackError

    engine = get_postgres_engine()
    baseline = engine.async_engine.pool.checkedout()
    session = engine.async_session_factory()
    try:
        await session.execute(text("SELECT 1"))
        connection = await session.connection()
        await connection.invalidate()
        assert session.in_transaction()
        # SQLAlchemy refuses reconnection until rollback, even if the ORM
        # session still describes an active transaction. The canonical
        # capture must not let this error replace the original failure.
        with pytest.raises(PendingRollbackError):
            (await session.connection()).sync_connection.connection
        await rollback_async_transaction(session)
        assert not session.in_transaction()
    finally:
        await session.close()

    assert engine.async_engine.pool.checkedout() == baseline
    async with engine.async_session_factory() as healthy:
        assert (await healthy.execute(text("SELECT 1"))).scalar_one() == 1
    assert engine.async_engine.pool.checkedout() == baseline


@pytest.mark.timeout(30)
async def test_live_logical_transaction_without_checkout_rolls_back_cleanly():
    """A transaction opened without SQL must not acquire a driver on cleanup."""
    from ai_karen_engine.persistence.postgres import transactions

    engine = get_postgres_engine()
    baseline = engine.async_engine.pool.checkedout()
    session = engine.async_session_factory()
    try:
        await session.begin()
        assert session.in_transaction()
        assert engine.async_engine.pool.checkedout() == baseline
        assert await transactions._capture_rollback_connection(session) is None
        assert engine.async_engine.pool.checkedout() == baseline
        await rollback_async_transaction(session)
        assert not session.in_transaction()
        assert engine.async_engine.pool.checkedout() == baseline
    finally:
        await session.close()
