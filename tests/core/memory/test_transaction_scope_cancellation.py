"""Cancellation must not strand an active canonical PostgreSQL transaction."""

import asyncio
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
        async with transactions.async_transaction_scope(tenant_id="tenant"):
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
        async with transactions.async_transaction_scope(tenant_id="tenant"):
            pass

    session.rollback.assert_awaited_once()
    session.__aexit__.assert_awaited_once()
