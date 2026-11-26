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
        await raw.execute(f'GRANT SELECT, UPDATE, DELETE ON public.conversations TO "{backend}"')
        await raw.execute(f'GRANT SELECT ON public.messages TO "{backend}"')
        await raw.execute(
            f'GRANT SELECT, INSERT, UPDATE ON public.runtime_chat_runs TO "{backend}"'
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

        # Promote only the test database through the canonical producer migration.
        # Keep the already-verified schema-77 assertions above intact.
        for filename in (
            "20261125010000_74_runtime_chat_single_active_run.sql",
            "20261125020000_75_runtime_chat_submission_identity.sql",
            "20261125030000_76_runtime_chat_unresolved_run.sql",
        ):
            await raw.execute(
                (ROOT / "supabase/migrations" / filename).read_text(encoding="utf-8")
            )
        await raw.execute(
            (ROOT / "supabase/migrations/20261126150739_78_communications_attention.sql").read_text(encoding="utf-8")
        )
        assert await raw.fetchval(
            "SELECT communications_attention_eligible_at IS NULL "
            "FROM runtime_chat_runs WHERE execution_id=$1", active_run,
        )
        with pytest.raises(asyncpg.CheckViolationError):
            await raw.execute(
                "UPDATE runtime_chat_runs SET communications_attention_eligible_at=terminal_at "
                "WHERE execution_id=$1", active_run,
            )

        # Exercise actual repository and privacy authority through the canonical SQLAlchemy transaction manager
        # and a non-owner / non-BYPASSRLS role.
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from ai_karen_engine.persistence.postgres import transactions
        from ai_karen_engine.persistence.repositories.communications_inbox_repository import (
            CommunicationsInboxRepository, InboxConflict, InboxFilter,
            InboxNotFound, InboxOperation,
        )
        from ai_karen_engine.services.privacy_compliance import DataEraser, DataExporter
        from ai_karen_engine.persistence.repositories import chat_run_repository

        new_run, foreign_run, foreign_conversation, historical_run = (uuid.uuid4() for _ in range(4))
        await raw.execute(
            "INSERT INTO conversations (conversation_id,tenant_id,user_id,title) "
            "VALUES ($1,$2,$3,'foreign private conversation')",
            foreign_conversation, tenant, other_owner,
        )
        await raw.execute("""
            INSERT INTO runtime_chat_runs (
                execution_id, tenant_id, user_id, conversation_id, transport_run_id,
                request_id, correlation_id, status, terminal_at
            ) VALUES ($1,$2,$3,$4,'historical','req','corr','failed',now())
        """, historical_run, tenant, owner, second_conversation)
        await raw.execute("""
            INSERT INTO runtime_chat_runs (
                execution_id, tenant_id, user_id, conversation_id, transport_run_id,
                request_id, correlation_id, status, lease_token, lease_expires_at,
                communications_attention_conversation_id
            ) VALUES ($1,$2,$3,$4,'new-failed','req','corr','running',$8,now()+interval '1 hour',$4),
                     ($5,$2,$6,$7,'foreign-failed','req','corr','running',$9,now()+interval '1 hour',$7)
        """, new_run, tenant, owner, second_conversation, foreign_run,
            other_owner, foreign_conversation, uuid.uuid4(), uuid.uuid4())
        await raw.execute("""
            UPDATE runtime_chat_runs SET status='failed', terminal_at=now(),
                lease_token=NULL, lease_expires_at=NULL,
                communications_attention_eligible_at=now()
            WHERE execution_id IN ($1,$2)
        """, new_run, foreign_run)
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
            with pytest.raises(InboxNotFound):
                await repo.admit_terminal_execution(
                    **principal, execution_id=str(historical_run),
                )
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

            # Three actual canonical ledger paths, without replacing its SQL.
            # Simulate a lost projection after durable terminal commit, then recover.
            feature = SimpleNamespace(enable_communications_terminal_producer=False)
            monkeypatch.setattr(chat_run_repository, "get_runtime_settings", lambda: SimpleNamespace(
                features=feature, timeouts=SimpleNamespace(chat_run_lease_seconds=120),
            ))
            ledger = chat_run_repository.SqlChatRunRepository()
            conversations = [uuid.uuid4() for _ in range(5)]
            await raw.executemany(
                "INSERT INTO conversations (conversation_id,tenant_id,user_id) VALUES ($1,$2,$3)",
                [(c, tenant, owner) for c in conversations],
            )

            async def admit(c, transport):
                return await ledger.admit(
                    **principal, conversation_id=str(c), transport_run_id=transport,
                    request_id="producer-req", correlation_id="producer-corr",
                )

            disabled = await admit(conversations[0], "disabled")
            assert disabled is not None
            assert await ledger.finish(disabled, status="failed")
            assert await raw.fetchval(
                "SELECT communications_attention_eligible_at IS NULL "
                "FROM runtime_chat_runs WHERE execution_id=$1", uuid.UUID(disabled.execution_id),
            )
            feature.enable_communications_terminal_producer = True

            # The marker shares the source transaction: rollback leaves no
            # eligible terminal evidence for reconciliation.
            rollback_run = await admit(conversations[0], "rollback")
            assert rollback_run is not None
            async with raw.transaction():
                await scope(raw, tenant, owner)
                savepoint = raw.transaction()
                await savepoint.start()
                await raw.execute(
                    "UPDATE runtime_chat_runs SET status='failed', terminal_at=now(), "
                    "lease_token=NULL, lease_expires_at=NULL, "
                    "communications_attention_eligible_at=now() WHERE execution_id=$1",
                    uuid.UUID(rollback_run.execution_id),
                )
                await savepoint.rollback()
            assert await raw.fetchval(
                "SELECT status='running' AND communications_attention_eligible_at IS NULL "
                "FROM runtime_chat_runs WHERE execution_id=$1", uuid.UUID(rollback_run.execution_id),
            )
            assert await repo.reconcile_pending(**principal) == 0

            failed = await admit(conversations[1], "failed")
            assert failed is not None

            async def projection_failure(*args, **kwargs):
                raise RuntimeError("private projection failure")
            with monkeypatch.context() as failure:
                failure.setattr(CommunicationsInboxRepository, "reconcile_pending", projection_failure)
                assert await ledger.finish(failed, status="failed")
            assert await raw.fetchval(
                "SELECT status FROM runtime_chat_runs WHERE execution_id=$1",
                uuid.UUID(failed.execution_id),
            ) == "failed"
            assert not (await repo.list_entries(**principal)).entries
            counts = await asyncio.gather(
                repo.reconcile_pending(**principal),
                repo.reconcile_pending(**principal),
            )
            assert sum(counts) == 1
            entry = (await repo.list_entries(**principal)).entries[0]
            assert entry.execution_id == failed.execution_id

            expired = await admit(conversations[2], "expired-admit")
            assert expired is not None
            await raw.execute(
                "UPDATE runtime_chat_runs SET lease_expires_at=now()-interval '1 second' "
                "WHERE execution_id=$1", uuid.UUID(expired.execution_id),
            )
            assert await admit(conversations[2], "must-not-restart") is None
            assert await raw.fetchval(
                "SELECT status FROM runtime_chat_runs WHERE execution_id=$1",
                uuid.UUID(expired.execution_id),
            ) == "orphaned"

            stopped = await admit(conversations[3], "expired-stop")
            assert stopped is not None
            await raw.execute(
                "UPDATE runtime_chat_runs SET lease_expires_at=now()-interval '1 second' "
                "WHERE execution_id=$1", uuid.UUID(stopped.execution_id),
            )
            assert await ledger.request_cancel(
                **principal, conversation_id=str(conversations[3]), transport_run_id="expired-stop",
            ) == "orphaned"
            assert await ledger.request_cancel(
                **principal, conversation_id=str(conversations[3]), transport_run_id="expired-stop",
            ) == "orphaned"

            cancelled = await admit(conversations[4], "cancelled")
            assert cancelled is not None
            assert await ledger.finish(cancelled, status="cancelled")
            assert {e.execution_id for e in (await repo.list_entries(**principal)).entries} == {
                failed.execution_id, expired.execution_id, stopped.execution_id,
            }
            assert await repo.reconcile_pending(**principal) == 0

            # A pending marker with erased source ownership may never recreate an entry.
            erased_conversation = uuid.uuid4()
            await raw.execute(
                "INSERT INTO conversations (conversation_id,tenant_id,user_id) VALUES ($1,$2,$3)",
                erased_conversation, tenant, owner,
            )
            erased_run = await admit(erased_conversation, "erased-pending")
            assert erased_run is not None
            with monkeypatch.context() as failure:
                failure.setattr(CommunicationsInboxRepository, "reconcile_pending", projection_failure)
                assert await ledger.finish(erased_run, status="failed")
            await raw.execute("DELETE FROM conversations WHERE conversation_id=$1", erased_conversation)
            assert await raw.fetchval(
                "SELECT communications_attention_conversation_id IS NULL "
                "AND communications_attention_eligible_at IS NOT NULL "
                "FROM runtime_chat_runs WHERE execution_id=$1", uuid.UUID(erased_run.execution_id),
            )
            # Even an explicit same-ID recreation cannot rebind an erased source.
            await raw.execute(
                "INSERT INTO conversations (conversation_id,tenant_id,user_id) VALUES ($1,$2,$3)",
                erased_conversation, tenant, owner,
            )
            with pytest.raises(asyncpg.CheckViolationError):
                await raw.execute(
                    "UPDATE runtime_chat_runs SET communications_attention_conversation_id=$1 "
                    "WHERE execution_id=$2", erased_conversation, uuid.UUID(erased_run.execution_id),
                )
            assert await repo.reconcile_pending(**principal) == 0
            assert len((await repo.list_entries(**principal)).entries) == 3
        finally:
            await engine.dispose()

        await raw.execute("DELETE FROM conversations WHERE tenant_id=$1 AND user_id=$2", tenant, owner)
        assert not await query(f"SELECT * FROM {table}")
        assert await raw.fetchval(
            "SELECT status FROM runtime_chat_runs WHERE execution_id=$1", active_run
        ) == "orphaned"
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
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
                    DROP FUNCTION IF EXISTS public.runtime_chat_communications_attention_guard();
                """)
                if await raw.fetchval(
                    "SELECT 1 FROM pg_roles WHERE rolname=$1", backend
                ):
                    await raw.execute(f'DROP OWNED BY "{backend}"')
                    await raw.execute(f'DROP ROLE "{backend}"')
        finally:
            await raw.close()
