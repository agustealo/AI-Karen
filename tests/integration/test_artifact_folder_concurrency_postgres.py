"""Real two-connection hierarchy proof on the existing disposable artifact DB."""
from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy.engine import make_url

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("KAREN_TEST_DISPOSABLE_DATABASE") != "1"
        or os.environ.get("KAREN_TEST_CODE_ARTIFACT_RLS") != "1",
        reason="Requires disposable artifact PostgreSQL proof",
    ),
]


def _dsn():
    url = make_url(os.environ["KAREN_TEST_CODE_ARTIFACT_DATABASE_URL"])
    assert url.drivername in ("postgresql", "postgresql+asyncpg")
    assert url.host in ("127.0.0.1", "localhost")
    assert url.port == 5432 and url.database == "karen_code_artifact_test"
    assert not url.query
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


_MOVE = "SELECT public.move_owned_artifact_folder($1,$2,$3,$4,$5)"


@pytest.mark.parametrize("isolation", ["read_committed", "repeatable_read"])
async def test_opposite_folder_moves_cannot_commit_cycle(isolation):
    tenant = UUID(os.environ["KAREN_TEST_ARTIFACT_TENANT_ID"])
    owner = UUID(os.environ["KAREN_TEST_ARTIFACT_OWNER_ID"])
    a, b = uuid4(), uuid4()
    first = await asyncpg.connect(_dsn())
    second = None
    try:
        second = await asyncpg.connect(_dsn())
        for conn in (first, second):
            await conn.execute("SET lock_timeout = '5s'")
            await conn.execute("SET statement_timeout = '10s'")
        await first.execute(
            "INSERT INTO public.artifact_folders "
            "(folder_id,tenant_id,owner_user_id,name) VALUES "
            "($1,$3,$4,'A'),($2,$3,$4,'B')",
            a, b, tenant, owner,
        )
        async with second.transaction(isolation=isolation):
            # Establish the second snapshot before the first mutation.
            assert await second.fetchval(
                "SELECT revision FROM public.artifact_folders WHERE folder_id=$1", b
            ) == 1
            async with first.transaction(isolation=isolation):
                assert await first.fetchval(_MOVE, tenant, owner, a, b, 1) == 2
                # The losing transaction must actually contend before release.
                async def opposite():
                    try:
                        async with second.transaction():
                            return await second.fetchval(_MOVE, tenant, owner, b, a, 1)
                    except (asyncpg.CheckViolationError,
                            asyncpg.SerializationError,
                            asyncpg.DeadlockDetectedError):
                        return None

                pending = asyncio.create_task(opposite())
                try:
                    for _ in range(100):
                        blocked = await first.fetchval(
                            "SELECT cardinality(pg_blocking_pids($1)) > 0",
                            second.get_server_pid(),
                        )
                        if blocked:
                            break
                        if pending.done():
                            pytest.fail("Opposing move completed before fence release")
                        await asyncio.sleep(0.02)
                    else:
                        pytest.fail("Opposing transaction never contended")
                except BaseException:
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                    raise
            assert await asyncio.wait_for(pending, timeout=12) is None
        rows = await first.fetch(
            "SELECT folder_id,parent_folder_id,revision FROM public.artifact_folders "
            "WHERE folder_id IN ($1,$2)", a, b,
        )
        state = {row["folder_id"]: (row["parent_folder_id"], row["revision"]) for row in rows}
        assert state == {a: (b, 2), b: (None, 1)}
        # A stale replay must not change the already committed tree.
        assert await first.fetchval(_MOVE, tenant, owner, a, None, 1) is None
    finally:
        if second is not None:
            await second.close()
        try:
            await first.execute(
                "DELETE FROM public.artifact_folders WHERE folder_id IN ($1,$2)", a, b
            )
        finally:
            await first.close()


@pytest.mark.parametrize("delete_account", [False, True])
async def test_artifact_move_after_concurrent_destination_removal(delete_account):
    """Deletion wins; a waiting assignment must never retain a dead folder."""
    tenant = UUID(os.environ["KAREN_TEST_ARTIFACT_TENANT_ID"])
    owner, folder = uuid4(), uuid4()
    artifact = str(uuid4())
    first = await asyncpg.connect(_dsn())
    second = None
    pending = None
    try:
        second = await asyncpg.connect(_dsn())
        for conn in (first, second):
            await conn.execute("SET lock_timeout = '5s'")
            await conn.execute("SET statement_timeout = '10s'")
        await first.execute(
            "INSERT INTO public.auth_users(user_id,tenant_id,email,roles) "
            "VALUES ($1,$2,$3,'[]'::jsonb)",
            owner, tenant, f"{owner}@ci.invalid",
        )
        await first.execute(
            "INSERT INTO public.artifact_folders(folder_id,tenant_id,owner_user_id,name) "
            "VALUES ($1,$2,$3,'Destination')", folder, tenant, owner,
        )
        uri = f"supabase://artifacts/{tenant}/{artifact}/content"
        await first.execute(
            "INSERT INTO public.files(file_id,tenant_id,owner_user_id,name,mime_type,"
            "bytes,storage_uri,sha256,metadata) "
            "VALUES ($1,$2,$3,'proof.txt','text/plain',42,$4,$5,'{}'::jsonb)",
            artifact, tenant, owner, uri, "a" * 64,
        )

        async def assign():
            try:
                return await second.fetchval(
                    "UPDATE public.files SET folder_id=$1 "
                    "WHERE file_id=$2 AND tenant_id=$3 AND owner_user_id=$4 "
                    "AND deleted_at IS NULL AND organization_revision=1 "
                    "RETURNING organization_revision",
                    folder, artifact, tenant, owner,
                )
            except (asyncpg.ForeignKeyViolationError, asyncpg.SerializationError,
                    asyncpg.DeadlockDetectedError):
                return None

        async with first.transaction():
            if delete_account:
                await first.execute("DELETE FROM public.auth_users WHERE user_id=$1", owner)
            else:
                await first.execute("DELETE FROM public.artifact_folders WHERE folder_id=$1", folder)
            pending = asyncio.create_task(assign())
            for _ in range(100):
                if await first.fetchval(
                    "SELECT cardinality(pg_blocking_pids($1)) > 0", second.get_server_pid()
                ):
                    break
                if pending.done():
                    pytest.fail("Assignment did not contend with uncommitted deletion")
                await asyncio.sleep(0.02)
            else:
                pytest.fail("Assignment never contended with deletion")
        assert await asyncio.wait_for(pending, timeout=12) is None
        row = await first.fetchrow(
            "SELECT tenant_id,owner_user_id,folder_id,organization_revision,storage_uri,sha256,bytes "
            "FROM public.files WHERE file_id=$1", artifact,
        )
        assert row is not None
        assert row["tenant_id"] == tenant
        assert row["owner_user_id"] == (None if delete_account else owner)
        assert row["folder_id"] is None and row["organization_revision"] == 1
        assert row["storage_uri"] == uri and row["sha256"] == "a" * 64 and row["bytes"] == 42
        assert not await first.fetchval(
            "SELECT EXISTS(SELECT 1 FROM public.artifact_folders WHERE folder_id=$1)", folder,
        )
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        if second is not None:
            await second.close()
        try:
            await first.execute("DELETE FROM public.files WHERE file_id=$1", artifact)
            await first.execute("DELETE FROM public.auth_users WHERE user_id=$1", owner)
        finally:
            await first.close()


async def test_scoped_repository_hierarchy_admission(monkeypatch):
    """Use canonical transaction scope on the disposable engine; no grants."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from ai_karen_engine.persistence.postgres import transactions
    from ai_karen_engine.services.database.repositories.supabase_artifact_store import (
        SupabaseArtifactStore,
    )
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    tenant = os.environ["KAREN_TEST_ARTIFACT_TENANT_ID"]
    owner = os.environ["KAREN_TEST_ARTIFACT_OWNER_ID"]
    engine = create_async_engine(make_url(_dsn()).set(drivername="postgresql+asyncpg"))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(transactions, "get_postgres_engine",
                        lambda: SimpleNamespace(async_session_factory=sessions))
    store = SupabaseArtifactStore(
        sessions, None, hierarchy_transaction=transactions.async_transaction_scope,
    )
    folder_id = None
    try:
        capability = await store.owner_hierarchy_available(tenant, owner)
        assert capability.success and capability.data is True
        created = await store.create_owner_folder(tenant, owner, name="Admission proof")
        assert created.success and created.data is not None
        folder_id = created.data.folder_id
        renamed = await store.rename_owner_folder(
            tenant, owner, folder_id, name="Renamed", expected_revision=1,
        )
        assert renamed.success and renamed.data.revision == 2
        stale = await store.rename_owner_folder(
            tenant, owner, folder_id, name="Stale", expected_revision=1,
        )
        assert not stale.success
        crumbs = await store.resolve_owner_breadcrumbs(tenant, owner, folder_id)
        assert crumbs.success and [f.name for f in crumbs.data] == ["Renamed"]

        @asynccontextmanager
        async def denied_scope(tenant_id, *, user_id):
            async with transactions.async_transaction_scope(tenant_id, user_id=user_id) as session:
                await session.execute(text("SET LOCAL ROLE ckgen_artifact_rls_actor"))
                yield session

        denied = SupabaseArtifactStore(sessions, None, hierarchy_transaction=denied_scope)
        assert not (await denied.owner_hierarchy_available(tenant, owner)).success
        assert not (await denied.create_owner_folder(tenant, owner, name="Denied")).success
        async with sessions() as session:
            assert (await session.execute(text(
                "SELECT current_user <> 'ckgen_artifact_rls_actor' "
                "AND COALESCE(current_setting('app.current_user_id', true),'') = ''"
            ))).scalar_one() is True
    finally:
        try:
            if folder_id:
                async with sessions.begin() as session:
                    await session.execute(text(
                        "DELETE FROM public.artifact_folders WHERE folder_id=CAST(:id AS uuid)"
                    ), {"id": folder_id})
        finally:
            await engine.dispose()


_DELETE_EMPTY = "SELECT public.delete_empty_owned_artifact_folder($1,$2,$3,$4)"


@pytest.mark.parametrize("assignment_first", [True, False])
@pytest.mark.parametrize("reference_kind", ["file", "folder"])
async def test_empty_folder_delete_serializes_destination_assignment(assignment_first, reference_kind):
    tenant = UUID(os.environ["KAREN_TEST_ARTIFACT_TENANT_ID"])
    owner = UUID(os.environ["KAREN_TEST_ARTIFACT_OWNER_ID"])
    destination, child = uuid4(), uuid4()
    artifact = str(uuid4())
    first = await asyncpg.connect(_dsn())
    second = None
    pending = None
    try:
        second = await asyncpg.connect(_dsn())
        for conn in (first, second):
            await conn.execute("SET lock_timeout = '5s'")
            await conn.execute("SET statement_timeout = '10s'")
        await first.execute(
            "INSERT INTO public.artifact_folders(folder_id,tenant_id,owner_user_id,name) "
            "VALUES ($1,$3,$4,'Destination'),($2,$3,$4,'Child')",
            destination, child, tenant, owner,
        )
        uri = f"supabase://artifacts/{tenant}/{artifact}/content"
        await first.execute(
            "INSERT INTO public.files(file_id,tenant_id,owner_user_id,name,mime_type,"
            "bytes,storage_uri,sha256,metadata) "
            "VALUES ($1,$2,$3,'proof.txt','text/plain',42,$4,$5,'{}'::jsonb)",
            artifact, tenant, owner, uri, "a" * 64,
        )

        async def assign(conn):
            try:
                if reference_kind == "folder":
                    return await conn.fetchval(_MOVE, tenant, owner, child, destination, 1)
                return await conn.fetchval(
                    "UPDATE public.files SET folder_id=$1 WHERE file_id=$2 "
                    "AND tenant_id=$3 AND owner_user_id=$4 AND organization_revision=1 "
                    "RETURNING organization_revision",
                    destination, artifact, tenant, owner,
                )
            except asyncpg.ForeignKeyViolationError:
                return None

        async def delete(conn):
            return await conn.fetchval(_DELETE_EMPTY, tenant, owner, destination, 1)

        async with first.transaction():
            if assignment_first:
                assert await assign(first) == 2
                pending = asyncio.create_task(delete(second))
            else:
                assert await delete(first) is True
                pending = asyncio.create_task(assign(second))
            for _ in range(100):
                if await first.fetchval(
                    "SELECT cardinality(pg_blocking_pids($1)) > 0", second.get_server_pid()
                ):
                    break
                if pending.done():
                    pytest.fail("Competing operation completed before lock release")
                await asyncio.sleep(0.02)
            else:
                pytest.fail("Competing operation never contended")
        assert await asyncio.wait_for(pending, timeout=12) is (False if assignment_first else None)
        row = await first.fetchrow(
            "SELECT folder_id,organization_revision,storage_uri,sha256,bytes "
            "FROM public.files WHERE file_id=$1", artifact,
        )
        assigned_file = assignment_first and reference_kind == "file"
        assert row["folder_id"] == (destination if assigned_file else None)
        assert row["organization_revision"] == (2 if assigned_file else 1)
        assert row["storage_uri"] == uri and row["sha256"] == "a" * 64 and row["bytes"] == 42
        assert await first.fetchval(
            "SELECT EXISTS(SELECT 1 FROM public.artifact_folders WHERE folder_id=$1)", destination
        ) is assignment_first
        assert await first.fetchval(
            "SELECT parent_folder_id FROM public.artifact_folders WHERE folder_id=$1", child
        ) == (destination if assignment_first and reference_kind == "folder" else None)
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        if second is not None:
            await second.close()
        try:
            await first.execute("DELETE FROM public.files WHERE file_id=$1", artifact)
            await first.execute("DELETE FROM public.artifact_folders WHERE folder_id IN ($1,$2)",
                                child, destination)
        finally:
            await first.close()


async def test_empty_folder_delete_rejects_stale_isolation():
    conn = await asyncpg.connect(_dsn())
    try:
        async with conn.transaction(isolation="repeatable_read"):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                async with conn.transaction():
                    await conn.fetchval(
                        _DELETE_EMPTY, UUID(os.environ["KAREN_TEST_ARTIFACT_TENANT_ID"]),
                        UUID(os.environ["KAREN_TEST_ARTIFACT_OWNER_ID"]), uuid4(), 1,
                    )
    finally:
        await conn.close()


async def test_real_folder_search_literal_owner_scope_and_keyset(monkeypatch):
    """Prove search and continuation against migrated PostgreSQL, not SQL mocks."""
    from types import SimpleNamespace

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ai_karen_engine.persistence.postgres import transactions
    from ai_karen_engine.services.database.repositories.supabase_artifact_store import (
        SupabaseArtifactStore,
    )

    tenant = UUID(os.environ["KAREN_TEST_ARTIFACT_TENANT_ID"])
    owner = UUID(os.environ["KAREN_TEST_ARTIFACT_OWNER_ID"])
    other = UUID(os.environ["KAREN_TEST_ARTIFACT_OTHER_USER_ID"])
    tenant_b = UUID(os.environ["KAREN_TEST_ARTIFACT_TENANT_B_ID"])
    owner_b = UUID(os.environ["KAREN_TEST_ARTIFACT_OWNER_B_ID"])
    folder, sibling, foreign = uuid4(), uuid4(), uuid4()
    marker = uuid4().hex
    query = marker + "%_"
    matching = [str(uuid4()) for _ in range(2)]
    fixtures = [
        (matching[0], tenant, owner, folder, query + "-one.txt", False),
        (matching[1], tenant, owner, folder, query.upper() + "-two.txt", False),
        (str(uuid4()), tenant, owner, folder, marker + "XY-decoy.txt", False),
        (str(uuid4()), tenant, owner, folder, query + "-deleted.txt", True),
        (str(uuid4()), tenant, owner, sibling, query + "-sibling.txt", False),
        (str(uuid4()), tenant, owner, None, query + "-root.txt", False),
        (str(uuid4()), tenant, other, foreign, query + "-foreign.txt", False),
        (str(uuid4()), tenant_b, owner_b, None, query + "-tenant.txt", False),
    ]
    engine = create_async_engine(make_url(_dsn()).set(drivername="postgresql+asyncpg"))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(
        transactions, "get_postgres_engine",
        lambda: SimpleNamespace(async_session_factory=sessions),
    )
    store = SupabaseArtifactStore(
        sessions, None, hierarchy_transaction=transactions.async_transaction_scope,
    )
    conn = None
    try:
        conn = await asyncpg.connect(_dsn())
        async with conn.transaction():
            await conn.executemany(
                "INSERT INTO public.artifact_folders "
                "(folder_id,tenant_id,owner_user_id,name) VALUES ($1,$2,$3,$4)",
                [(folder, tenant, owner, marker + "-folder"),
                 (sibling, tenant, owner, marker + "-sibling"),
                 (foreign, tenant, other, marker + "-foreign")],
            )
            for file_id, file_tenant, file_owner, parent, name, deleted in fixtures:
                await conn.execute(
                    "INSERT INTO public.files "
                    "(file_id,tenant_id,owner_user_id,folder_id,name,mime_type,"
                    "bytes,storage_uri,sha256,metadata,deleted_at) "
                    "VALUES ($1,$2,$3,$4,$5,'text/plain',42,$6,$7,'{}'::jsonb,"
                    "CASE WHEN $8::boolean THEN now() ELSE NULL END)",
                    file_id, file_tenant, file_owner, parent, name,
                    f"supabase://artifacts/{file_tenant}/{file_id}/content",
                    "a" * 64, deleted,
                )

        options = dict(folder_scoped=True, folder_id=str(folder), search=query, limit=1)
        first = await store.list_owner_artifacts_page(str(tenant), str(owner), **options)
        assert first.success and len(first.data) == 1
        assert first.metadata["has_more"] is True
        cursor = first.metadata["next_cursor"]
        assert isinstance(cursor, str) and cursor
        second = await store.list_owner_artifacts_page(
            str(tenant), str(owner), cursor=cursor, **options,
        )
        assert second.success and len(second.data) == 1
        assert second.metadata == {"has_more": False, "next_cursor": None}
        assert {first.data[0].id, second.data[0].id} == set(matching)
        for artifact in (first.data[0], second.data[0]):
            assert artifact.tenant_id == str(tenant)
            assert artifact.user_id == str(owner)
            assert artifact.folder_id == str(folder)
            assert artifact.organization_revision == 1

        for principal_tenant, principal_owner, changes in (
            (tenant, owner, {"search": marker}),
            (tenant, owner, {"folder_id": str(sibling)}),
            (tenant, owner, {"folder_id": None}),
            (tenant, owner, {"folder_scoped": False, "folder_id": None}),
            (tenant, other, {"folder_id": str(foreign)}),
            (tenant_b, owner_b, {"folder_id": None}),
        ):
            replay = await store.list_owner_artifacts_page(
                str(principal_tenant), str(principal_owner), cursor=cursor,
                **{**options, **changes},
            )
            assert not replay.success
            assert replay.error == "artifact_owner_page_invalid: artifact_owner_cursor_invalid"

        denied = await store.list_owner_artifacts_page(
            str(tenant), str(owner), **{**options, "folder_id": str(foreign)},
        )
        assert not denied.success
        root = await store.list_owner_artifacts_page(
            str(tenant), str(owner), **{**options, "folder_id": None},
        )
        assert root.success
        assert [artifact.id for artifact in root.data] == [fixtures[5][0]]
        assert root.metadata == {"has_more": False, "next_cursor": None}
    finally:
        try:
            if conn is not None:
                try:
                    async with conn.transaction():
                        await conn.executemany(
                            "DELETE FROM public.files WHERE file_id=$1",
                            [(fixture[0],) for fixture in fixtures],
                        )
                        await conn.execute(
                            "DELETE FROM public.artifact_folders "
                            "WHERE folder_id IN ($1,$2,$3)", folder, sibling, foreign,
                        )
                finally:
                    await conn.close()
        finally:
            await engine.dispose()

async def _insert_depth_chain(conn, tenant, owner, folders):
    parent = None
    for folder in folders:
        await conn.execute(
            "INSERT INTO public.artifact_folders "
            "(folder_id,tenant_id,owner_user_id,parent_folder_id,name) "
            "VALUES ($1,$2,$3,$4,'Depth fixture')",
            folder, tenant, owner, parent,
        )
        parent = folder


async def test_hierarchy_depth_boundary_and_subtree_move(monkeypatch):
    """The database guard and real breadcrumb reader agree at the boundary."""
    from types import SimpleNamespace

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ai_karen_engine.persistence.postgres import transactions
    from ai_karen_engine.services.database.repositories.supabase_artifact_store import (
        SupabaseArtifactStore,
    )

    tenant = UUID(os.environ["KAREN_TEST_ARTIFACT_TENANT_ID"])
    owner = UUID(os.environ["KAREN_TEST_ARTIFACT_OWNER_ID"])
    chain = [uuid4() for _ in range(64)]
    root, child, rejected_id = uuid4(), uuid4(), uuid4()
    rejected_name = rejected_id.hex
    engine = create_async_engine(make_url(_dsn()).set(drivername="postgresql+asyncpg"))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(
        transactions, "get_postgres_engine",
        lambda: SimpleNamespace(async_session_factory=sessions),
    )
    store = SupabaseArtifactStore(
        sessions, None, hierarchy_transaction=transactions.async_transaction_scope,
    )
    conn = None
    try:
        conn = await asyncpg.connect(_dsn())
        async with conn.transaction():
            await _insert_depth_chain(conn, tenant, owner, chain)
            await _insert_depth_chain(conn, tenant, owner, [root, child])
        principal = (str(tenant), str(owner))
        boundary = await store.resolve_owner_breadcrumbs(*principal, str(chain[-1]))
        assert boundary.success
        assert [f.folder_id for f in boundary.data] == [str(f) for f in chain]

        # A raw SQL writer cannot bypass the invariant.
        with pytest.raises(asyncpg.CheckViolationError, match="artifact_folder_depth_exceeded"):
            await conn.execute(
                "INSERT INTO public.artifact_folders "
                "(folder_id,tenant_id,owner_user_id,parent_folder_id,name) "
                "VALUES ($1,$2,$3,$4,$5)",
                rejected_id, tenant, owner, chain[-1], rejected_name,
            )
        rejected = await store.create_owner_folder(
            *principal, name=rejected_name, parent_folder_id=str(chain[-1]),
        )
        assert not rejected.success
        assert rejected.error == "artifact_folder_conflict_or_unavailable"

        # The moved root would fit at 64, but its child would not.
        rejected_move = await store.move_owner_folder(
            *principal, str(root), parent_folder_id=str(chain[62]), expected_revision=1,
        )
        assert not rejected_move.success
        assert rejected_move.error == "artifact_folder_conflict_or_unavailable"
        original = await conn.fetchrow(
            "SELECT parent_folder_id,revision FROM public.artifact_folders WHERE folder_id=$1",
            root,
        )
        assert original["parent_folder_id"] is None and original["revision"] == 1
        assert not await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM public.artifact_folders "
            "WHERE tenant_id=$1 AND owner_user_id=$2 AND name=$3)",
            tenant, owner, rejected_name,
        )

        # Exactly 64 levels remains navigable, with untouched child revision.
        moved = await store.move_owner_folder(
            *principal, str(root), parent_folder_id=str(chain[61]), expected_revision=1,
        )
        assert moved.success and moved.data == 2
        breadcrumbs = await store.resolve_owner_breadcrumbs(*principal, str(child))
        assert breadcrumbs.success
        assert [f.folder_id for f in breadcrumbs.data] == [
            str(f) for f in [*chain[:62], root, child]
        ]
        assert breadcrumbs.data[-1].revision == 1
        moved_to_root = await store.move_owner_folder(
            *principal, str(root), parent_folder_id=None, expected_revision=2,
        )
        assert moved_to_root.success and moved_to_root.data == 3
        restored = await store.resolve_owner_breadcrumbs(*principal, str(child))
        assert restored.success
        assert [f.folder_id for f in restored.data] == [str(root), str(child)]
    finally:
        try:
            if conn is not None:
                try:
                    await conn.execute(
                        "DELETE FROM public.artifact_folders WHERE folder_id=ANY($1::uuid[]) "
                        "OR (tenant_id=$2 AND owner_user_id=$3 AND name=$4)",
                        [*chain, root, child, rejected_id], tenant, owner, rejected_name,
                    )
                finally:
                    await conn.close()
        finally:
            await engine.dispose()


@pytest.mark.parametrize("isolation", ["read_committed", "repeatable_read"])
async def test_concurrent_folder_moves_cannot_exceed_depth(isolation):
    """Two individually valid moves must not combine into an invalid hierarchy."""
    tenant = UUID(os.environ["KAREN_TEST_ARTIFACT_TENANT_ID"])
    owner = UUID(os.environ["KAREN_TEST_ARTIFACT_OWNER_ID"])
    chain = [uuid4() for _ in range(62)]
    root, child, incoming = uuid4(), uuid4(), uuid4()
    first = await asyncpg.connect(_dsn())
    second = None
    pending = None
    try:
        second = await asyncpg.connect(_dsn())
        for conn in (first, second):
            await conn.execute("SET lock_timeout = '5s'")
            await conn.execute("SET statement_timeout = '10s'")
        async with first.transaction():
            await _insert_depth_chain(first, tenant, owner, chain)
            await _insert_depth_chain(first, tenant, owner, [root, child])
            await _insert_depth_chain(first, tenant, owner, [incoming])
        async with second.transaction(isolation=isolation):
            assert await second.fetchval(
                "SELECT revision FROM public.artifact_folders WHERE folder_id=$1", incoming,
            ) == 1
            async with first.transaction(isolation=isolation):
                assert await first.fetchval(_MOVE, tenant, owner, root, chain[-1], 1) == 2

                async def competing_move():
                    try:
                        async with second.transaction():
                            await second.fetchval(_MOVE, tenant, owner, incoming, child, 1)
                    except asyncpg.CheckViolationError as exc:
                        assert "artifact_folder_depth_exceeded" in str(exc)
                        return
                    except asyncpg.SerializationError:
                        assert isolation == "repeatable_read"
                        return
                    pytest.fail("Concurrent move exceeded the hierarchy depth")

                pending = asyncio.create_task(competing_move())
                for _ in range(100):
                    if await first.fetchval(
                        "SELECT cardinality(pg_blocking_pids($1)) > 0", second.get_server_pid(),
                    ):
                        break
                    if pending.done():
                        pytest.fail("Competing move completed before fence release")
                    await asyncio.sleep(0.02)
                else:
                    pytest.fail("Competing move never contended")
            await asyncio.wait_for(pending, timeout=12)
        rows = await first.fetch(
            "SELECT folder_id,parent_folder_id,revision FROM public.artifact_folders "
            "WHERE folder_id IN ($1,$2,$3)", root, child, incoming,
        )
        assert {row["folder_id"]: (row["parent_folder_id"], row["revision"]) for row in rows} == {
            root: (chain[-1], 2), child: (root, 1), incoming: (None, 1),
        }
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        if second is not None:
            await second.close()
        try:
            await first.execute(
                "DELETE FROM public.artifact_folders WHERE folder_id=ANY($1::uuid[])",
                [*chain, root, child, incoming],
            )
        finally:
            await first.close()
