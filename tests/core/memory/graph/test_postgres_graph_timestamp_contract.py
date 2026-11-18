"""Contract tests for canonical temporal graph persistence in PostgreSQL.

MemoryRelation uses TIMESTAMP WITHOUT TIME ZONE. The graph domain keeps
timezone-aware UTC instants, but this repository must serialize them as
UTC-normalized naive timestamps before binding through asyncpg.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from ai_karen_engine.core.memory.graph.models import GraphEdge
from ai_karen_engine.platform.memory.postgres import graph_repository
from ai_karen_engine.platform.memory.postgres.graph_repository import (
    PostgresGraphRepository,
    PostgresGraphScopeError,
)
from ai_karen_engine.platform.memory.postgres.ledger_models import MemoryRelation


@pytest.mark.parametrize(
    ("input_value", "expected"),
    [
        (
            datetime(2026, 11, 18, 10, 16, 35, tzinfo=timezone.utc),
            datetime(2026, 11, 18, 10, 16, 35),
        ),
        (
            datetime(
                2026, 11, 18, 15, 46, 35,
                tzinfo=timezone(timedelta(hours=5, minutes=30)),
            ),
            datetime(2026, 11, 18, 10, 16, 35),
        ),
        (
            "2026-11-18T15:46:35+05:30",
            datetime(2026, 11, 18, 10, 16, 35),
        ),
        (
            "2026-11-18T10:16:35Z",
            datetime(2026, 11, 18, 10, 16, 35),
        ),
        (
            datetime(2026, 11, 18, 10, 16, 35),
            datetime(2026, 11, 18, 10, 16, 35),
        ),
    ],
)
def test_temporal_storage_normalizes_utc_without_timezone(input_value, expected):
    value = PostgresGraphRepository._datetime(input_value, "observed_at")
    assert value == expected
    assert value.tzinfo is None


def test_missing_and_malformed_temporal_fields_fail_closed():
    assert PostgresGraphRepository._datetime(None, "recorded_at") is None
    with pytest.raises(PostgresGraphScopeError, match="ISO-8601 datetime"):
        PostgresGraphRepository._datetime("not-a-timestamp", "recorded_at")
    with pytest.raises(PostgresGraphScopeError, match="must be a datetime"):
        PostgresGraphRepository._datetime(123, "recorded_at")


@pytest.mark.asyncio
async def test_create_edge_binds_only_utc_naive_timestamps(monkeypatch):
    """Inspect the ORM write boundary without replacing canonical logic."""
    class _Result:
        @staticmethod
        def scalar_one_or_none():
            return None

    class _Session:
        def __init__(self):
            self.added = []

        async def execute(self, statement):
            return _Result()

        def add(self, row):
            self.added.append(row)

    session = _Session()

    @asynccontextmanager
    async def scope(*, tenant_id):
        assert tenant_id == tenant
        yield session

    monkeypatch.setattr(graph_repository, "async_transaction_scope", scope)

    tenant = str(uuid4())
    user = str(uuid4())
    offset = timezone(timedelta(hours=5, minutes=30))
    edge = GraphEdge(
        from_id=str(uuid4()),
        to_id=str(uuid4()),
        relationship="MENTIONS",
        tenant_id=tenant,
        user_id=user,
        conversation_id=str(uuid4()),
        valid_from=datetime(2026, 11, 18, 15, 46, tzinfo=offset),
        valid_to=datetime(2026, 11, 19, 15, 46, tzinfo=offset),
        observed_at=datetime(2026, 11, 18, 15, 47, tzinfo=offset),
        recorded_at=datetime(2026, 11, 18, 15, 48, tzinfo=offset),
    )
    await PostgresGraphRepository().create_edge(edge)

    assert len(session.added) == 1
    row = session.added[0]
    assert isinstance(row, MemoryRelation)
    assert row.valid_from == datetime(2026, 11, 18, 10, 16)
    assert row.valid_to == datetime(2026, 11, 19, 10, 16)
    assert row.observed_at == datetime(2026, 11, 18, 10, 17)
    assert row.recorded_at == datetime(2026, 11, 18, 10, 18)
    for field in ("valid_from", "valid_to", "observed_at", "recorded_at"):
        assert getattr(row, field).tzinfo is None
        assert getattr(MemoryRelation, field).type.timezone is False


@pytest.mark.asyncio
async def test_default_recorded_at_is_utc_naive(monkeypatch):
    class _Result:
        @staticmethod
        def scalar_one_or_none():
            return None

    class _Session:
        row = None

        async def execute(self, statement):
            return _Result()

        def add(self, row):
            self.row = row

    session = _Session()

    @asynccontextmanager
    async def scope(*, tenant_id):
        assert tenant_id == tenant
        yield session

    monkeypatch.setattr(graph_repository, "async_transaction_scope", scope)

    tenant = str(uuid4())
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    await PostgresGraphRepository().create_edge(
        GraphEdge(
            from_id=str(uuid4()),
            to_id=str(uuid4()),
            relationship="MENTIONS",
            tenant_id=tenant,
            user_id=str(uuid4()),
        )
    )
    after = datetime.now(timezone.utc).replace(tzinfo=None)

    assert session.row is not None
    assert session.row.recorded_at.tzinfo is None
    assert before <= session.row.recorded_at <= after
