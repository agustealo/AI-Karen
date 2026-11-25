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
