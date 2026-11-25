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


def test_root_page_cursor_cannot_replay_across_scopes():
    store, session = _store([_row(3), _row(2)])
    first = _run(store.list_owner_artifacts_page(
        TENANT, OWNER, limit=1, folder_scoped=True,
    ))
    assert first.success
    cursor = first.metadata["next_cursor"]
    sql, params = session.calls[-1]
    assert "folder_id IS NOT DISTINCT FROM CAST(:folder_id AS uuid)" in sql
    assert params["folder_id"] is None
    assert "organization_revision" in sql
    count = len(session.calls)
    for options in (
        {"folder_scoped": False},
        {"folder_scoped": True, "folder_id": str(uuid.uuid4())},
        {"folder_scoped": False, "folder_id": str(uuid.uuid4())},
    ):
        result = _run(store.list_owner_artifacts_page(
            TENANT, OWNER, cursor=cursor, **options,
        ))
        assert not result.success
    assert len(session.calls) == count
    assert _run(store.list_owner_artifacts_page(
        TENANT, OWNER, cursor=cursor, folder_scoped=True,
    )).success


def test_flat_cursor_cannot_enter_root_inventory():
    store, session = _store([_row(3), _row(2)])
    first = _run(store.list_owner_artifacts_page(TENANT, OWNER, limit=1))
    count = len(session.calls)
    result = _run(store.list_owner_artifacts_page(
        TENANT, OWNER, folder_scoped=True, cursor=first.metadata["next_cursor"],
    ))
    assert not result.success
    assert len(session.calls) == count


class _HierarchySession(_Session):
    def __init__(self, scalar=None, rows=(), fail_commit=False):
        super().__init__(rows)
        self.scalar = scalar
        self.fail_commit = fail_commit
        self.commits = 0

    async def execute(self, statement, params):
        self.calls.append((str(statement), dict(params)))
        return SimpleNamespace(
            scalar_one_or_none=lambda: self.scalar,
            fetchall=lambda: self.rows,
        )

    async def commit(self):
        self.commits += 1
        if self.fail_commit:
            raise RuntimeError("uncertain commit")


def _hierarchy_store(session):
    return SupabaseArtifactStore(lambda: session, None)


def test_foreign_folder_fails_before_inventory_read():
    session = _HierarchySession()
    result = _run(_hierarchy_store(session).list_owner_artifacts_page(
        TENANT, OWNER, folder_scoped=True, folder_id=str(uuid.uuid4()),
    ))
    assert not result.success
    assert result.error == "artifact_hierarchy_unavailable"
    assert len(session.calls) == 1
    sql, params = session.calls[0]
    assert "FOR KEY SHARE" in sql
    assert "owner_user_id" in sql
    assert params["user_id"] == OWNER


def test_folder_page_projects_organization_and_binds_continuation():
    folder = str(uuid.uuid4())
    rows = [_row(3), _row(2)]
    for row in rows:
        row.folder_id = uuid.UUID(folder)
        row.organization_revision = 7
    session = _HierarchySession(scalar=uuid.UUID(folder), rows=rows)
    store = _hierarchy_store(session)
    result = _run(store.list_owner_artifacts_page(
        TENANT, OWNER, folder_scoped=True, folder_id=folder, limit=1,
    ))
    assert result.success
    assert result.data[0].folder_id == folder
    assert result.data[0].organization_revision == 7
    assert len(session.calls) == 2
    count = len(session.calls)
    assert not _run(store.list_owner_artifacts_page(
        TENANT, OWNER, folder_scoped=True, folder_id=str(uuid.uuid4()),
        cursor=result.metadata["next_cursor"],
    )).success
    assert len(session.calls) == count


def test_artifact_movement_commits_only_valid_revision():
    artifact_id, folder_id = str(uuid.uuid4()), str(uuid.uuid4())
    for returned, expected_success in ((None, False), (9, False), (2, True), (3, True)):
        session = _HierarchySession(scalar=returned)
        result = _run(_hierarchy_store(session).move_owner_artifact(
            TENANT, OWNER, artifact_id, folder_id=folder_id, expected_revision=2,
        ))
        assert result.success is expected_success
        assert session.commits == int(expected_success)
        sql, params = session.calls[0]
        assert "deleted_at IS NULL" in sql
        assert "owner_user_id = CAST(:owner AS uuid)" in sql
        assert "organization_revision = :revision" in sql
        assert params == {
            "tenant": TENANT, "owner": OWNER, "artifact": artifact_id,
            "folder": folder_id, "revision": 2,
        }


def test_invalid_mutation_result_unwinds_autocommit_session():
    class AutoCommitSession(_HierarchySession):
        async def __aexit__(self, exc_type, exc, tb):
            if exc_type is None:
                await self.commit()
            return False

    session = AutoCommitSession(scalar=99)
    result = _run(_hierarchy_store(session).move_owner_artifact(
        TENANT, OWNER, str(uuid.uuid4()), folder_id=None, expected_revision=1,
    ))
    assert not result.success
    assert session.commits == 0


def test_uncertain_movement_commit_is_not_retried():
    session = _HierarchySession(scalar=2, fail_commit=True)
    result = _run(_hierarchy_store(session).move_owner_artifact(
        TENANT, OWNER, str(uuid.uuid4()), folder_id=None, expected_revision=1,
    ))
    assert not result.success
    assert result.error == "artifact_folder_commit_uncertain"
    assert session.commits == 1
    assert len(session.calls) == 1


def test_invalid_hierarchy_mutations_do_not_execute_sql():
    session = _HierarchySession()
    store = _hierarchy_store(session)
    artifact = str(uuid.uuid4())
    for revision in (True, 0, -1, 9223372036854775807):
        assert not _run(store.move_owner_artifact(
            TENANT, OWNER, artifact, folder_id=None, expected_revision=revision,
        )).success
    assert not _run(store.create_owner_folder(TENANT, OWNER, name=" bad ")).success
    assert not _run(store.rename_owner_folder(
        TENANT, OWNER, artifact, name="bad\x00name", expected_revision=1,
    )).success
    assert session.calls == []
