"""Raw graph event references must respect canonical current consent.

The graph projection is a candidate source, not a second authorization owner.
PostgresEventSource enforces the scoped live memory-event consent predicate.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from ai_karen_engine.platform.memory.postgres import graph_repository
from ai_karen_engine.platform.memory.postgres.graph_repository import PostgresGraphRepository


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _Session:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, statement, parameters):
        assert parameters["result_limit"] > 0
        return _Rows(self.rows)


class _CanonicalEvents:
    def __init__(self, recallable_ids):
        self.recallable_ids = recallable_ids
        self.calls = []

    async def fetch_many(self, *, tenant_id, user_id, event_ids):
        self.calls.append((tenant_id, user_id, list(event_ids)))
        return {event_id: {"event_id": event_id}
                for event_id in event_ids if event_id in self.recallable_ids}


@pytest.mark.asyncio
async def test_graph_traversal_drops_revoked_events_before_returning_raw_ids(monkeypatch):
    tenant_id, user_id = str(uuid4()), str(uuid4())
    visible_id, revoked_id = str(uuid4()), str(uuid4())
    rows = [
        {"event_id": visible_id, "relationship": "MENTIONS", "depth": 1},
        {"event_id": revoked_id, "relationship": "MENTIONS", "depth": 1},
    ]
    session = _Session(rows)
    @asynccontextmanager
    async def scoped_transaction(*, tenant_id: str):
        assert tenant_id == expected_tenant
        yield session

    expected_tenant = tenant_id
    canonical = _CanonicalEvents({visible_id})
    monkeypatch.setattr(graph_repository, "async_transaction_scope", scoped_transaction)
    monkeypatch.setattr(graph_repository, "PostgresEventSource", lambda: canonical)
    repository = PostgresGraphRepository()

    result = await repository.find_related_events(
        tenant_id=tenant_id, user_id=user_id, event_id=str(uuid4()),
    )
    assert [row["event_id"] for row in result] == [visible_id]
    assert canonical.calls == [(tenant_id, user_id, [visible_id, revoked_id])]

    canonical.recallable_ids.clear()
    assert await repository.find_related_events(
        tenant_id=tenant_id, user_id=user_id, event_id=str(uuid4()),
    ) == []


@pytest.mark.asyncio
async def test_raw_graph_fails_closed_when_canonical_consent_lookup_fails(monkeypatch):
    tenant_id, user_id, event_id = str(uuid4()), str(uuid4()), str(uuid4())
    @asynccontextmanager
    async def scoped_transaction(*, tenant_id: str):
        yield _Session([{
            "event_id": event_id, "relationship": "MENTIONS", "depth": 1,
        }])

    class _UnavailableEvents:
        async def fetch_many(self, **kwargs):
            raise RuntimeError("consent database unavailable")

    monkeypatch.setattr(graph_repository, "async_transaction_scope", scoped_transaction)
    monkeypatch.setattr(graph_repository, "PostgresEventSource", _UnavailableEvents)

    with pytest.raises(RuntimeError, match="consent database unavailable"):
        await PostgresGraphRepository().find_related_events(
            tenant_id=tenant_id, user_id=user_id, event_id=str(uuid4()),
        )
