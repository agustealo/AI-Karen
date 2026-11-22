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



@pytest.mark.asyncio
async def test_noncooperative_rollback_is_reported_uncertain_not_success():
    """A cancellation-resistant driver must never produce a clean receipt."""
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    session = MagicMock()

    async def noncooperative_rollback():
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            # Simulate a driver that ignores cancellation until I/O resolves.
            await release.wait()
        finally:
            finished.set()

    session.rollback = AsyncMock(side_effect=noncooperative_rollback)
    session.invalidate = AsyncMock(return_value=None)
    task = asyncio.create_task(rollback_async_transaction(session))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        with pytest.raises(RuntimeError, match="connection_uncertain"):
            await asyncio.wait_for(task, timeout=3)
        # Concurrent invalidation is forbidden while rollback is still
        # active; deferred retirement owns invalidation after it completes.
        session.invalidate.assert_not_awaited()
        assert not finished.is_set()
    finally:
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=2)



@pytest.mark.asyncio
async def test_invalidation_never_overlaps_active_noncooperative_rollback():
    """Regression for SQLAlchemy's concurrent transaction-state transition guard."""
    rollback_started = asyncio.Event()
    release_rollback = asyncio.Event()
    rollback_finished = asyncio.Event()
    overlap = []
    session = MagicMock()

    async def rollback():
        rollback_started.set()
        try:
            await release_rollback.wait()
        except asyncio.CancelledError:
            await release_rollback.wait()
        finally:
            rollback_finished.set()

    async def invalidate():
        if not rollback_finished.is_set():
            overlap.append("invalidate_during_rollback")
            raise RuntimeError("IllegalStateChangeError: rollback still active")

    session.rollback = AsyncMock(side_effect=rollback)
    session.invalidate = AsyncMock(side_effect=invalidate)
    task = asyncio.create_task(rollback_async_transaction(session))
    try:
        await asyncio.wait_for(rollback_started.wait(), timeout=1)
        with pytest.raises((RuntimeError, TimeoutError)):
            await asyncio.wait_for(task, timeout=3)
        assert not overlap, (
            "SQLAlchemy invalidation raced an active rollback; "
            "the connection cannot be assumed quarantined"
        )
    finally:
        release_rollback.set()
        await asyncio.wait_for(rollback_finished.wait(), timeout=2)


@pytest.mark.asyncio
async def test_nested_quarantined_rollback_is_not_retried_or_closed():
    """An existing retirement owner is authoritative across scope unwinding."""
    from ai_karen_engine.persistence.postgres import transactions

    session = MagicMock()
    session.execute = AsyncMock()
    session.rollback = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.async_session_factory.return_value = session
    original = RuntimeError("postgres_rollback_unresponsive_connection_uncertain_quarantined")

    with patch.object(transactions, "get_postgres_engine", return_value=engine), patch.object(
        transactions, "rollback_async_transaction", new_callable=AsyncMock
    ) as rollback:
        with pytest.raises(RuntimeError, match="connection_uncertain"):
            async with transactions.async_transaction_scope():
                raise original
        rollback.assert_awaited_once()

    # The test above raises an ordinary RuntimeError; the scope delegates
    # once to its canonical rollback owner and closes the session.
    session.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_quarantined_rollback_from_nested_owner_skips_second_cleanup():
    """A true _RollbackStillActive arriving from the body owns its session."""
    from ai_karen_engine.persistence.postgres import transactions

    session = MagicMock()
    session.execute = AsyncMock()
    session.rollback = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.async_session_factory.return_value = session
    task = asyncio.create_task(asyncio.sleep(0))
    pending = transactions._RollbackStillActive(task)

    try:
        with patch.object(transactions, "get_postgres_engine", return_value=engine), patch.object(
            transactions, "rollback_async_transaction", new_callable=AsyncMock
        ) as rollback:
            with pytest.raises(transactions._RollbackStillActive) as caught:
                async with transactions.async_transaction_scope():
                    raise pending
            assert caught.value is pending
            rollback.assert_not_awaited()
        session.__aexit__.assert_not_awaited()
    finally:
        await task


@pytest.mark.asyncio
async def test_detach_failure_still_assigns_rollback_retirement_owner():
    """A stale pool proxy must not enable concurrent session close."""
    from ai_karen_engine.persistence.postgres import transactions

    rollback_task = asyncio.create_task(asyncio.sleep(0))
    pending = transactions._RollbackStillActive(rollback_task)
    session = MagicMock()
    session.rollback = AsyncMock()
    session.invalidate = AsyncMock()
    session.close = AsyncMock()

    async def failed_cleanup(operation, *, seconds, label):
        # The supervisor is mocked here; explicitly close its incoming
        # coroutine so a never-awaited AsyncMock does not leak from the test.
        operation.close()
        raise pending

    with patch.object(
        transactions, "_capture_rollback_connection", new_callable=AsyncMock,
        return_value=object(),
    ), patch.object(
        transactions, "_bounded_transaction_cleanup",
        side_effect=failed_cleanup,
    ), patch.object(
        transactions, "_detach_pending_rollback_connection",
        side_effect=RuntimeError("pool proxy already invalidated"),
    ):
        with pytest.raises(transactions._RollbackStillActive) as caught:
            await transactions.rollback_async_transaction(session)
    assert caught.value is pending
    assert pending.retirement_task is not None
    await asyncio.wait_for(pending.retirement_task, timeout=2)
    session.invalidate.assert_awaited_once()
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_detach_failure_defers_session_teardown_until_rollback_finishes():
    """Even a broken pool proxy cannot authorize concurrent session mutation."""
    from ai_karen_engine.persistence.postgres import transactions

    release = asyncio.Event()
    entered = asyncio.Event()
    finished = asyncio.Event()
    session = MagicMock()
    invalidation_during_rollback = []

    async def blocked_rollback():
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        finally:
            finished.set()

    async def invalidate():
        if not finished.is_set():
            invalidation_during_rollback.append(True)

    session.rollback = AsyncMock(side_effect=blocked_rollback)
    session.invalidate = AsyncMock(side_effect=invalidate)
    session.close = AsyncMock()
    with patch.object(
        transactions, "_capture_rollback_connection", new_callable=AsyncMock,
        return_value=object(),
    ), patch.object(
        transactions, "_detach_pending_rollback_connection",
        side_effect=RuntimeError("pool proxy unavailable"),
    ):
        task = asyncio.create_task(transactions.rollback_async_transaction(session))
        pending = None
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            with pytest.raises(transactions._RollbackStillActive) as caught:
                await asyncio.wait_for(task, timeout=3)
            pending = caught.value
            assert pending.retirement_task is not None
            assert not finished.is_set()
            session.invalidate.assert_not_awaited()
            session.close.assert_not_awaited()
        finally:
            release.set()
            await asyncio.wait_for(finished.wait(), timeout=2)
            if pending is not None and pending.retirement_task is not None:
                await asyncio.wait_for(pending.retirement_task, timeout=2)
    assert not invalidation_during_rollback
    session.invalidate.assert_awaited_once()
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_rollback_preflight_never_acquires_new_connection():
    """A logical transaction with no owned connection must not check out."""
    from ai_karen_engine.persistence.postgres import transactions

    session = MagicMock(spec=transactions.AsyncSession)
    # sync_session is an instance attribute, not part of the class spec.
    session.sync_session = MagicMock()
    session.in_transaction.return_value = True
    session.is_active = True
    transaction = MagicMock()
    transaction._connections = {}
    session.sync_session.get_transaction.return_value = transaction
    session.connection = AsyncMock(
        side_effect=AssertionError("rollback preflight checked out connection")
    )

    owned = await transactions._capture_rollback_connection(session)

    assert owned is None
    session.connection.assert_not_awaited()


@pytest.mark.asyncio
async def test_rollback_preflight_uses_existing_connection_only():
    """Existing checked-out physical connection is read without session I/O."""
    from ai_karen_engine.persistence.postgres import transactions

    session = MagicMock(spec=transactions.AsyncSession)
    # sync_session is an instance attribute, not part of the class spec.
    session.sync_session = MagicMock()
    session.in_transaction.return_value = True
    session.is_active = True
    connection = MagicMock()
    proxy = object()
    connection.connection = proxy
    transaction = MagicMock()
    transaction._connections = {object(): (connection, None, True, False)}
    session.sync_session.get_transaction.return_value = transaction
    session.connection = AsyncMock(
        side_effect=AssertionError("session.connection() must not run")
    )

    assert await transactions._capture_rollback_connection(session) is proxy
    session.connection.assert_not_awaited()
