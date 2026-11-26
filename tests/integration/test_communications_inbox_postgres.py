"""KCOMM-02A canonical migration proof; never run against an application database."""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest

pytestmark = pytest.mark.asyncio
ROOT = Path(__file__).resolve().parents[2]


async def test_communications_inbox_real_postgres() -> None:
    if (
        os.environ.get("KAREN_TEST_COMMUNICATIONS_POSTGRES") != "1"
        or os.environ.get("KAREN_TEST_DISPOSABLE_DATABASE") != "1"
    ):
        pytest.skip("Explicit disposable PostgreSQL opt-in required")
    dsn = os.environ.get("KAREN_TEST_COMMUNICATIONS_DATABASE_URL")
    if not dsn or urlparse(dsn).path != "/karen_communications_test":
        pytest.fail("Expected dedicated /karen_communications_test database")
    if urlparse(dsn).hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("Communications inbox proof requires local PostgreSQL")

    raw = await asyncpg.connect(dsn)
    backend = "comm_backend_" + uuid.uuid4().hex[:12]
    tenant, other_tenant, owner, other_owner = (uuid.uuid4() for _ in range(4))
    conversation, second_conversation, execution, active_run = (
        uuid.uuid4() for _ in range(4)
    )

    async def scope(
        conn: asyncpg.Connection, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        await conn.execute(f'SET LOCAL ROLE "{backend}"')
        await conn.execute(
            "SELECT set_config('app.current_tenant_id', $1, true), "
            "set_config('app.current_user_id', $2, true)",
            str(tenant_id), str(user_id),
        )

    async def query(
        sql: str, *args: object, tenant_id: uuid.UUID = tenant,
        user_id: uuid.UUID = owner,
    ) -> list[asyncpg.Record]:
        async with raw.transaction():
            await scope(raw, tenant_id, user_id)
            return await raw.fetch(sql, *args)

    created = False
    try:
        if await raw.fetchval(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
        ):
            pytest.fail("Refuse any existing public application schema")

        # Minimal dependency fixtures only. The real source-key migrations and
        # the canonical communications migration provide the constraints under test.
        await raw.execute("""
            CREATE TABLE public.tenants (id uuid PRIMARY KEY);
            CREATE TABLE public.auth_users (user_id uuid PRIMARY KEY);
            CREATE TABLE public.conversations (
                conversation_id uuid PRIMARY KEY,
                tenant_id uuid NOT NULL REFERENCES public.tenants(id),
                user_id uuid NOT NULL REFERENCES public.auth_users(user_id)
            );
            CREATE TABLE public.messages (
                message_id uuid PRIMARY KEY,
                conversation_id uuid NOT NULL REFERENCES public.conversations(conversation_id)
                    ON DELETE CASCADE
            );
        """)
        created = True
        for filename in (
            "20261025020000_43_runtime_chat_run_ledger.sql",
            "20261025050000_46_runtime_chat_event_journal.sql",
            "20261118213000_64_kui_presentation_pin_references.sql",
        ):
            await raw.execute(
                (ROOT / "supabase/migrations" / filename).read_text(encoding="utf-8")
            )
        await raw.execute(
            (ROOT / "supabase/migrations/20261126144509_77_communications_inbox.sql").read_text(encoding="utf-8")
        )
        await raw.execute(f'CREATE ROLE "{backend}" NOLOGIN NOBYPASSRLS')
        await raw.execute(f'GRANT USAGE ON SCHEMA public TO "{backend}"')
        await raw.execute(
            f'GRANT SELECT ON public.runtime_chat_runs TO "{backend}"'
        )
        await raw.execute(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON public.communications_inbox_entries '
            f'TO "{backend}"'
        )
        await raw.execute("INSERT INTO tenants VALUES ($1), ($2)", tenant, other_tenant)
        await raw.execute("INSERT INTO auth_users VALUES ($1), ($2)", owner, other_owner)
        await raw.execute(
            "INSERT INTO conversations VALUES ($1,$2,$3),($4,$2,$3)",
            conversation, tenant, owner, second_conversation,
        )
        await raw.execute("""
            INSERT INTO runtime_chat_runs (
                execution_id, tenant_id, user_id, conversation_id, transport_run_id,
                request_id, correlation_id, status, terminal_at
            ) VALUES ($1,$2,$3,$4,'failed-run','req','corr','failed',now())
        """, execution, tenant, owner, conversation)
        await raw.execute("""
            INSERT INTO runtime_chat_runs (
                execution_id, tenant_id, user_id, conversation_id, transport_run_id,
                request_id, correlation_id, status, lease_token, lease_expires_at
            ) VALUES ($1,$2,$3,$4,'active-run','req','corr','running',$5,now()+interval '1 hour')
        """, active_run, tenant, owner, conversation, uuid.uuid4())

        table = "public.communications_inbox_entries"
        insert = (
            f"INSERT INTO {table} (tenant_id,user_id,conversation_id,execution_id) "
            "VALUES ($1,$2,$3,$4) RETURNING *"
        )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await query(insert, tenant, owner, conversation, active_run)
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await query(insert, tenant, owner, second_conversation, execution)
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await query(insert, tenant, owner, conversation, execution,
                        user_id=other_owner)

        # The composite FK also protects privileged SQL that bypasses RLS.
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await raw.fetch(insert, tenant, owner, second_conversation, execution)

        row = (await query(insert, tenant, owner, conversation, execution))[0]
        entry_id = row["entry_id"]
        assert row["revision"] == 1
        assert row["read_at"] is None and row["archived_at"] is None
        with pytest.raises(asyncpg.UniqueViolationError):
            await query(insert, tenant, owner, conversation, execution)
        for scoped_tenant, scoped_user in ((tenant, other_owner), (other_tenant, owner)):
            assert not await query(
                f"SELECT * FROM {table}", tenant_id=scoped_tenant, user_id=scoped_user
            )
            assert not await query(
                f"UPDATE {table} SET read_at=now(), revision=2 RETURNING entry_id",
                tenant_id=scoped_tenant, user_id=scoped_user,
            )
        async with raw.transaction():
            await raw.execute(f'SET LOCAL ROLE "{backend}"')
            assert await raw.fetchval(f"SELECT count(*) FROM {table}") == 0

        for setting, value in (
            ("app.current_tenant_id", str(tenant)),
            ("app.current_user_id", str(owner)),
        ):
            async with raw.transaction():
                await raw.execute(f'SET LOCAL ROLE "{backend}"')
                await raw.execute("SELECT set_config($1, $2, true)", setting, value)
                assert await raw.fetchval(f"SELECT count(*) FROM {table}") == 0

        for role in ("anon", "authenticated"):
            if await raw.fetchval("SELECT 1 FROM pg_roles WHERE rolname=$1", role):
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert not await raw.fetchval(
                        "SELECT has_table_privilege($1,$2,$3)", role, table, privilege
                    )
                assert not await raw.fetchval(
                    "SELECT has_function_privilege($1,$2,'EXECUTE')",
                    role, "public.communications_inbox_lifecycle_guard()",
                )

        with pytest.raises(asyncpg.CheckViolationError):
            await query(
                f"UPDATE {table} SET conversation_id=$1, revision=2, read_at=now() "
                "WHERE entry_id=$2", second_conversation, entry_id,
            )
        with pytest.raises(asyncpg.CheckViolationError):
            await query(f"UPDATE {table} SET revision=2 WHERE entry_id=$1", entry_id)

        # Explicit acknowledgment implies read and ignores client-supplied time.
        ack = (await query(
            f"UPDATE {table} SET acknowledged_at='2000-01-01', revision=revision+1 "
            "WHERE entry_id=$1 AND revision=1 RETURNING *", entry_id,
        ))[0]
        assert ack["read_at"] == ack["acknowledged_at"] >= row["created_at"]
        assert ack["archived_at"] is None and ack["revision"] == 2
        assert not await query(
            f"UPDATE {table} SET archived_at=now(), revision=revision+1 "
            "WHERE entry_id=$1 AND revision=1 RETURNING entry_id", entry_id,
        )
        with pytest.raises(asyncpg.CheckViolationError):
            await query(
                f"UPDATE {table} SET read_at=NULL, revision=3 WHERE entry_id=$1", entry_id,
            )
        # A rollback must not fabricate durable state.
        async with raw.transaction():
            await scope(raw, tenant, owner)
            savepoint = raw.transaction()
            await savepoint.start()
            await raw.execute(
                f"UPDATE {table} SET archived_at=now(), revision=3 WHERE entry_id=$1",
                entry_id,
            )
            await savepoint.rollback()
            assert await raw.fetchval(
                f"SELECT revision FROM {table} WHERE entry_id=$1", entry_id
            ) == 2
        async def archive_once(conn: asyncpg.Connection) -> list[asyncpg.Record]:
            async with conn.transaction():
                await scope(conn, tenant, owner)
                return await conn.fetch(
                    f"UPDATE {table} SET archived_at=now(), revision=revision+1 "
                    "WHERE entry_id=$1 AND revision=2 RETURNING *", entry_id,
                )

        peer = await asyncpg.connect(dsn)
        try:
            outcomes = await asyncio.gather(archive_once(raw), archive_once(peer))
        finally:
            await peer.close()
        assert sorted(len(result) for result in outcomes) == [0, 1]
        archived = next(result[0] for result in outcomes if result)
        assert archived["revision"] == 3
        assert archived["acknowledged_at"] == ack["acknowledged_at"]
        assert not await query(f"DELETE FROM {table} RETURNING entry_id")

        # Source deletion cascades without modifying the source's other state.
        await raw.execute("DELETE FROM runtime_chat_runs WHERE execution_id=$1", execution)
        assert not await query(f"SELECT * FROM {table}")
        await raw.execute(
            "UPDATE runtime_chat_runs SET status='orphaned', terminal_at=now(), "
            "lease_token=NULL, lease_expires_at=NULL WHERE execution_id=$1", active_run,
        )
        orphan = (await query(insert, tenant, owner, conversation, active_run))[0]
        archive_only = (await query(
            f"UPDATE {table} SET archived_at=now(), revision=revision+1 "
            "WHERE entry_id=$1 AND revision=1 RETURNING *", orphan["entry_id"],
        ))[0]
        assert archive_only["read_at"] is None
        assert archive_only["acknowledged_at"] is None
        await raw.execute("DELETE FROM conversations WHERE conversation_id=$1", conversation)
        assert not await query(f"SELECT * FROM {table}")
        assert await raw.fetchval(
            "SELECT status FROM runtime_chat_runs WHERE execution_id=$1", active_run
        ) == "orphaned"
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await query(insert, tenant, owner, conversation, active_run)
    finally:
        try:
            if created:
                await raw.execute("""
                    DROP TABLE IF EXISTS public.communications_inbox_entries,
                        public.conversation_presentation_pins, public.runtime_chat_run_events,
                        public.runtime_chat_runs, public.messages, public.conversations,
                        public.auth_users, public.tenants CASCADE;
                    DROP FUNCTION IF EXISTS public.communications_inbox_lifecycle_guard();
                """)
                if await raw.fetchval(
                    "SELECT 1 FROM pg_roles WHERE rolname=$1", backend
                ):
                    await raw.execute(f'DROP OWNED BY "{backend}"')
                    await raw.execute(f'DROP ROLE "{backend}"')
        finally:
            await raw.close()
