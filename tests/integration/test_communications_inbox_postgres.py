"""KCOMM-02A canonical migration proof; never run against an application database."""
from __future__ import annotations

import asyncio
import os
import uuid
from types import SimpleNamespace
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest

pytestmark = pytest.mark.asyncio
ROOT = Path(__file__).resolve().parents[2]


async def test_communications_inbox_real_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
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
                user_id uuid NOT NULL REFERENCES public.auth_users(user_id),
                title text, conversation_metadata jsonb, is_active bool DEFAULT true,
                created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now(),
                session_id uuid, summary text, tags jsonb
            );
            CREATE TABLE public.messages (
                message_id uuid PRIMARY KEY,
                conversation_id uuid NOT NULL REFERENCES public.conversations(conversation_id)
                    ON DELETE CASCADE,
                role text, content text, message_metadata jsonb,
                created_at timestamptz DEFAULT now()
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
        await raw.execute(f'GRANT SELECT, DELETE ON public.conversations TO "{backend}"')
        await raw.execute(f'GRANT SELECT ON public.messages TO "{backend}"')
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
            "INSERT INTO conversations (conversation_id,tenant_id,user_id) "
            "VALUES ($1,$2,$3),($4,$2,$3)",
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

        # Exercise actual repository and privacy authority against the same
        # migration, through the canonical SQLAlchemy transaction manager
        # and a non-owner / non-BYPASSRLS role.
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from ai_karen_engine.persistence.postgres import transactions
        from ai_karen_engine.persistence.repositories.communications_inbox_repository import (
            CommunicationsInboxRepository, InboxConflict, InboxFilter,
            InboxNotFound, InboxOperation,
        )
        from ai_karen_engine.services.privacy_compliance import DataEraser, DataExporter

        new_run, foreign_run, foreign_conversation = (uuid.uuid4() for _ in range(3))
        await raw.execute(
            "INSERT INTO conversations (conversation_id,tenant_id,user_id,title) "
            "VALUES ($1,$2,$3,'foreign private conversation')",
            foreign_conversation, tenant, other_owner,
        )
        await raw.execute("""
            INSERT INTO runtime_chat_runs (
                execution_id, tenant_id, user_id, conversation_id, transport_run_id,
                request_id, correlation_id, status, terminal_at
            ) VALUES ($1,$2,$3,$4,'new-failed','req','corr','failed',now()),
                     ($5,$2,$6,$7,'foreign-failed','req','corr','failed',now())
        """, new_run, tenant, owner, second_conversation, foreign_run,
            other_owner, foreign_conversation)
        engine = create_async_engine(
            dsn.replace("postgresql://", "postgresql+asyncpg://", 1),
            connect_args={"server_settings": {"role": backend}},
        )
        maker = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(
            transactions, "get_postgres_engine",
            lambda: SimpleNamespace(async_session_factory=maker),
        )
        repo = CommunicationsInboxRepository()
        principal = {"tenant_id": str(tenant), "user_id": str(owner)}
        foreign_principal = {"tenant_id": str(tenant), "user_id": str(other_owner)}
        try:
            first, second = await asyncio.gather(
                repo.admit_terminal_execution(**principal, execution_id=str(new_run)),
                repo.admit_terminal_execution(**principal, execution_id=str(new_run)),
            )
            assert first == second
            foreign = await repo.admit_terminal_execution(
                **foreign_principal, execution_id=str(foreign_run),
            )
            with pytest.raises(InboxNotFound):
                await repo.admit_terminal_execution(
                    **principal, execution_id=str(foreign_run),
                )
            page = await repo.list_entries(
                **principal, limit=1, inbox_filter=InboxFilter.ALL,
            )
            assert page.active_unread_count == 1
            assert page.next_cursor is not None
            next_page = await repo.list_entries(
                **principal, limit=1, inbox_filter=InboxFilter.ALL,
                cursor=page.next_cursor,
            )
            assert next_page.next_cursor is None
            assert {page.entries[0].entry_id, next_page.entries[0].entry_id} == {
                first.entry_id, str(orphan["entry_id"]),
            }
            with pytest.raises(InboxNotFound):
                await repo.mutate(
                    **principal, entry_id=foreign.entry_id,
                    operation=InboxOperation.READ, expected_revision=1,
                )
            outcomes = await asyncio.gather(*(
                repo.mutate(
                    **principal, entry_id=first.entry_id,
                    operation=InboxOperation.ACKNOWLEDGE, expected_revision=1,
                ) for _ in range(2)
            ))
            assert sorted(item.changed for item in outcomes) == [False, True]
            assert outcomes[0].entry == outcomes[1].entry
            assert outcomes[0].entry.revision == 2
            with pytest.raises(InboxConflict):
                await repo.mutate(
                    **principal, entry_id=first.entry_id,
                    operation=InboxOperation.ARCHIVE, expected_revision=1,
                )
            with pytest.raises(InboxConflict):
                await repo.mutate(
                    **principal, entry_id=first.entry_id,
                    operation=InboxOperation.READ, expected_revision=99,
                )
            assert (await repo.list_entries(**principal)).active_unread_count == 0
            # Redelivery after archival must not recreate an active entry.
            replay = await repo.admit_terminal_execution(
                **principal, execution_id=str(active_run),
            )
            assert replay.entry_id == str(orphan["entry_id"])
            assert replay.archived_at is not None
            async with transactions.async_transaction_scope(**principal) as session:
                exported = await DataExporter(db_client=object())._export_conversations(
                    session, str(owner), str(tenant), False,
                )
                exported_ids = {
                    entry["source_kind"] for item in exported
                    for entry in item["communications_inbox"]
                }
                assert exported_ids == {"terminal_chat_attention"}
                assert sum(len(item["communications_inbox"]) for item in exported) == 2
                assert "foreign private conversation" not in str(exported)
                assert "terminal_error_code" not in str(exported)
                erased = await DataEraser(db_client=object())._erase_conversations(
                    session, **principal,
                )
                assert "communications_inbox_entries" in erased["cascade_includes"]
                assert erased["affected_records"] == 2
            assert not (await repo.list_entries(
                **principal, inbox_filter=InboxFilter.ALL,
            )).entries
            assert (await repo.list_entries(**foreign_principal)).entries == (foreign,)
            with pytest.raises(InboxNotFound):
                await repo.admit_terminal_execution(
                    **principal, execution_id=str(active_run),
                )
        finally:
            await engine.dispose()

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
