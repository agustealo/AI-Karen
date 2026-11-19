"""Owner-scoped ArtifactStore cursor and query contract.

These isolated tests inspect the actual production query and result shape.
Live PostgreSQL performance and full UI acceptance are separate gates.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from ai_karen_engine.services.database.repositories.supabase_artifact_store import (
    SupabaseArtifactStore,
)

TENANT = str(uuid.uuid4())
OWNER = str(uuid.uuid4())
OTHER_TENANT = str(uuid.uuid4())
OTHER_OWNER = str(uuid.uuid4())
NOW = datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)


def _row(number: int):
    return SimpleNamespace(
        file_id=uuid.UUID(int=number + 1),
        tenant_id=uuid.UUID(TENANT),
        owner_user_id=uuid.UUID(OWNER),
        name=f"private-{number}.txt",
        mime_type="text/plain",
        bytes=42,
        storage_uri=f"supabase://artifacts/private/{number}",
        sha256="a" * 64,
        metadata={},
        created_at=NOW,
        deleted_at=None,
    )


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement, params):
        self.calls.append((str(statement), dict(params)))
        return SimpleNamespace(fetchall=lambda: self.rows)


def _store(rows):
    session = _Session(rows)
    store = SupabaseArtifactStore(
        session_factory=lambda: session,
        storage_client=None,
    )
    return store, session


def _run(coro):
    return asyncio.run(coro)


def test_owner_page_uses_bounded_db_side_tenant_and_owner_query():
    store, session = _store([_row(2), _row(1), _row(0)])
    result = _run(store.list_owner_artifacts_page(TENANT, OWNER, limit=2))
    assert result.success
    assert len(result.data) == 2
    assert result.metadata["has_more"] is True
    assert isinstance(result.metadata["next_cursor"], str)
    assert all(row.user_id == OWNER and row.tenant_id == TENANT for row in result.data)

    sql, params = session.calls[0]
    assert "tenant_id = :tenant_id" in sql
    assert "owner_user_id = :user_id" in sql
    assert "deleted_at IS NULL" in sql
    assert "ORDER BY created_at DESC, file_id DESC" in sql
    assert "LIMIT :page_limit" in sql
    assert params == {
        "tenant_id": TENANT, "user_id": OWNER, "page_limit": 3,
    }


def test_cursor_uses_keyset_and_is_bound_to_both_principals():
    store, session = _store([_row(3), _row(2)])
    first = _run(store.list_owner_artifacts_page(TENANT, OWNER, limit=1))
    cursor = first.metadata["next_cursor"]
    second = _run(store.list_owner_artifacts_page(
        TENANT, OWNER, limit=1, cursor=cursor,
    ))
    assert second.success
    sql, params = session.calls[-1]
    assert "created_at < :before_created" in sql
    assert "file_id < :before_id" in sql
    assert params["before_created"] == NOW
    assert params["before_id"] == str(uuid.UUID(int=4))
    assert params["tenant_id"] == TENANT
    assert params["user_id"] == OWNER

    original_call_count = len(session.calls)
    assert not _run(store.list_owner_artifacts_page(
        TENANT, OTHER_OWNER, limit=1, cursor=cursor,
    )).success
    assert not _run(store.list_owner_artifacts_page(
        OTHER_TENANT, OWNER, limit=1, cursor=cursor,
    )).success
    assert len(session.calls) == original_call_count


def test_missing_continuation_returns_terminal_page_metadata():
    store, _session = _store([_row(0)])
    result = _run(store.list_owner_artifacts_page(TENANT, OWNER, limit=2))
    assert result.success
    assert result.metadata == {"has_more": False, "next_cursor": None}


def test_unscoped_and_malformed_requests_never_query_storage():
    store, session = _store([])
    requests = [
        ("default", OWNER, 1, None),
        (TENANT, "default", 1, None),
        (TENANT, OWNER, 0, None),
        (TENANT, OWNER, True, None),
        (TENANT, OWNER, 201, None),
        (TENANT, OWNER, 1, "/../"),
        (TENANT, OWNER, 1, "!!!"),
        (TENANT, OWNER, 1, "A" * 769),
    ]
    for tenant, owner, limit, cursor in requests:
        result = _run(store.list_owner_artifacts_page(
            tenant, owner, limit=limit, cursor=cursor,
        ))
        assert not result.success
        assert result.data is None
    assert session.calls == []


def test_repository_errors_fail_closed_without_fabricated_empty_page():
    class BrokenSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement, params):
            raise RuntimeError("database unavailable")

    store = SupabaseArtifactStore(
        session_factory=lambda: BrokenSession(),
        storage_client=None,
    )
    result = _run(store.list_owner_artifacts_page(TENANT, OWNER))
    assert result.success is False
    assert result.error == "artifact_owner_page_unavailable"
    assert result.data is None
