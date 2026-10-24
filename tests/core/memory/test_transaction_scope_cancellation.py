"""Cancellation must not strand an active canonical PostgreSQL transaction."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_karen_engine.persistence.postgres import transactions


@pytest.mark.asyncio
async def test_async_transaction_scope_rolls_back_when_caller_cancelled(monkeypatch):
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.async_session_factory.return_value = session
    monkeypatch.setattr(transactions, "get_postgres_engine", lambda: engine)

    with pytest.raises(asyncio.CancelledError):
        async with transactions.async_transaction_scope(tenant_id="11111111-1111-4111-8111-111111111111"):
            raise asyncio.CancelledError()

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    session.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_transaction_scope_rolls_back_when_commit_cancelled(monkeypatch):
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock(side_effect=asyncio.CancelledError())
    session.rollback = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.async_session_factory.return_value = session
    monkeypatch.setattr(transactions, "get_postgres_engine", lambda: engine)

    with pytest.raises(asyncio.CancelledError):
        async with transactions.async_transaction_scope(tenant_id="11111111-1111-4111-8111-111111111111"):
            pass

    session.rollback.assert_awaited_once()
    session.__aexit__.assert_awaited_once()

@pytest.mark.asyncio
async def test_canonical_rollback_waits_for_interrupted_cleanup():
    started = asyncio.Event()
    release = asyncio.Event()
    session = MagicMock()

    async def delayed_rollback():
        started.set()
        await release.wait()

    session.rollback = AsyncMock(side_effect=delayed_rollback)
    session.invalidate = AsyncMock()
    task = asyncio.create_task(transactions.rollback_async_transaction(session))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    await task
    session.rollback.assert_awaited_once()
    session.invalidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_canonical_rollback_invalidates_failed_session():
    session = MagicMock()
    session.rollback = AsyncMock(side_effect=RuntimeError("rollback failed"))
    session.invalidate = AsyncMock()
    with pytest.raises(RuntimeError, match="rollback failed"):
        await transactions.rollback_async_transaction(session)
    session.invalidate.assert_awaited_once()

@pytest.mark.asyncio
async def test_transaction_scope_binds_principal_after_tenant_context(monkeypatch):
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.async_session_factory.return_value = session
    monkeypatch.setattr(transactions, "get_postgres_engine", lambda: engine)

    principal = str(uuid.uuid4())
    async with transactions.async_transaction_scope(
        tenant_id="11111111-1111-4111-8111-111111111111", user_id=principal,
    ):
        pass

    statements = [str(call.args[0]) for call in session.execute.await_args_list]
    assert "app.current_user_id" in statements[-1]
    assert session.execute.await_args_list[-1].args[1] == {"user": principal}
    assert len(statements) == 3
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("11111111-1111-4111-8111-111111111111", "principal"),
    [(None, str(uuid.uuid4())), ("invalid-tenant", str(uuid.uuid4())),
     ("11111111-1111-4111-8111-111111111111", ""), ("11111111-1111-4111-8111-111111111111", "   "),
     ("11111111-1111-4111-8111-111111111111", "not-a-uuid")],
)
async def test_transaction_scope_rejects_unscoped_principal(monkeypatch, tenant, principal):
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.async_session_factory.return_value = session
    monkeypatch.setattr(transactions, "get_postgres_engine", lambda: engine)

    with pytest.raises(ValueError):
        async with transactions.async_transaction_scope(
            tenant_id=tenant, user_id=principal,
        ):
            pass

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
