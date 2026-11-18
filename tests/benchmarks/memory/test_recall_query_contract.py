"""KCOG-RESEARCH-01: compiled SQL safety probes for canonical recall.

These tests inspect generated SQL without claiming to have queried a live DB.
Native pgvector/FTS execution must be proven separately with real PostgreSQL.
"""

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from ai_karen_engine.core.memory.types import MemoryQuery
from ai_karen_engine.platform.memory.postgres.recall_retriever import (
    PostgresRecallRetriever,
    PostgresRecallScopeError,
)


class _Rows:
    def all(self):
        return []


class _CaptureSession:
    def __init__(self):
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _Rows()


@pytest.mark.asyncio
async def test_canonical_recall_sql_keeps_scoping_consent_and_validity() -> None:
    session = _CaptureSession()

    @asynccontextmanager
    async def factory():
        yield session

    query = MemoryQuery(
        text="What did we decide about search?",
        tenant_id=str(uuid4()),
        user_id=str(uuid4()),
        top_k=5,
    )

    result = await PostgresRecallRetriever(session_factory=factory).recall(query)
    assert result == []
    assert session.statement is not None

    compiled = str(session.statement.compile(dialect=postgresql.dialect()))
    for required in (
        "memory_assertion.tenant_id",
        "memory_assertion.user_id",
        "memory_assertion.consent_state",
        "memory_assertion.valid_from",
        "memory_assertion.valid_to",
        "memory_event",
    ):
        assert required in compiled, f"Missing governed SQL criterion: {required}"

    # This test deliberately does not require LIKE, FTS or vector expressions:
    # replacing a legacy substring search with a safer semantic backend
    # must not be forbidden by research-only regression tests.
    assert "what did we decide about search?" not in compiled.lower()


@pytest.mark.asyncio
async def test_canonical_recall_rejects_invalid_scope_before_query() -> None:
    session = _CaptureSession()

    @asynccontextmanager
    async def factory():
        yield session

    retriever = PostgresRecallRetriever(session_factory=factory)
    for tenant_id, user_id in (
        ("", str(uuid4())),
        (str(uuid4()), ""),
        ("not-a-uuid", str(uuid4())),
    ):
        with pytest.raises(PostgresRecallScopeError):
            await retriever.recall(
                MemoryQuery(
                    text="private memory",
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
            )
    assert session.statement is None
