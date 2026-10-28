"""Real PostgreSQL proof for CK-07B, on a dedicated disposable database only.

Set CHAT_RUN_TEST_DATABASE_URL with database name EXACTLY karen_chat_run_test.
The test recreates the canonical run ledger in that dedicated database.
No production database is ever accepted.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.persistence.repositories import chat_run_repository as module
from ai_karen_engine.persistence.repositories.chat_run_repository import SqlChatRunRepository
from ai_karen_engine.services.database.repositories.conversation_repository import (
    Message, canonical_message_digest,
)
from ai_karen_engine.services.database.repositories.postgres_conversation_repository import (
    PostgresConversationRepository,
)


@pytest.mark.asyncio
async def test_real_postgres_exact_run_stop_and_terminal_race(monkeypatch):
    url = os.getenv("CHAT_RUN_TEST_DATABASE_URL")
    if not url:
        pytest.skip("CHAT_RUN_TEST_DATABASE_URL not configured (real DB proof NOT run)")
    if urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1)).path != (
        "/karen_chat_run_test"
    ):
        pytest.fail("Refusing to mutate a database other than karen_chat_run_test")

    dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    raw = await asyncpg.connect(dsn)
    engine = None
    tenant_a, tenant_b, user_a, user_b, thread = (
        str(uuid.uuid4()) for _ in range(5)
    )

    try:
        await raw.execute(
            """
            DROP TABLE IF EXISTS public.runtime_chat_runs CASCADE;
            DROP TABLE IF EXISTS public.messages CASCADE;
            DROP TABLE IF EXISTS public.conversations CASCADE;
            DROP TABLE IF EXISTS public.auth_users CASCADE;
            DROP TABLE IF EXISTS public.tenants CASCADE;
            CREATE TABLE public.tenants (id uuid PRIMARY KEY);
            CREATE TABLE public.auth_users (
                user_id uuid PRIMARY KEY,
                tenant_id uuid NOT NULL REFERENCES public.tenants(id)
            );
            CREATE TABLE public.conversations (
                conversation_id uuid PRIMARY KEY,
                tenant_id uuid NOT NULL REFERENCES public.tenants(id),
                user_id uuid NOT NULL REFERENCES public.auth_users(user_id)
            );
            CREATE TABLE public.messages (
                message_id uuid PRIMARY KEY,
                conversation_id uuid NOT NULL REFERENCES public.conversations(conversation_id),
                role text NOT NULL,
                content text NOT NULL,
                message_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
                created_at timestamptz NOT NULL DEFAULT now()
            );
            """
        )
        migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261025020000_43_runtime_chat_run_ledger.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(migration)
        replay_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261025030000_44_runtime_chat_replay_identity.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(replay_migration)
        digest_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261025040000_45_runtime_chat_replay_digest.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(digest_migration)
        event_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261025050000_46_runtime_chat_event_journal.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(event_migration)
        draft_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261026010000_47_conversation_composer_drafts.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(draft_migration)
        await raw.execute(
            "INSERT INTO public.tenants(id) VALUES($1),($2)",
            uuid.UUID(tenant_a), uuid.UUID(tenant_b),
        )
        await raw.execute(
            """
            INSERT INTO public.auth_users(user_id, tenant_id)
            VALUES ($1,$2),($3,$4)
            """,
            uuid.UUID(user_a), uuid.UUID(tenant_a),
            uuid.UUID(user_b), uuid.UUID(tenant_b),
        )

        await raw.execute(
            """
            INSERT INTO public.conversations(conversation_id,tenant_id,user_id)
            VALUES ($1,$2,$3)
            """,
            uuid.UUID(thread), uuid.UUID(tenant_a), uuid.UUID(user_a),
        )

        engine = create_async_engine(
            "postgresql+asyncpg://" + dsn.split("://", 1)[1],
            pool_size=5, max_overflow=0,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)

        @asynccontextmanager
        async def real_scope(tenant_id: str, *, user_id: str):
            async with factory() as session:
                async with session.begin():
                    await session.execute(
                        text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                        {"tenant": tenant_id},
                    )
                    await session.execute(
                        text("SELECT set_config('app.current_user_id', :owner, true)"),
                        {"owner": user_id},
                    )
                    yield session

        monkeypatch.setattr(module, "async_transaction_scope", real_scope)
        worker_a, worker_b = SqlChatRunRepository(), SqlChatRunRepository()
        conversations = PostgresConversationRepository(factory)

        def identity(owner=user_a, tenant=tenant_a, run_id="run-one"):
            return {
                "tenant_id": tenant,
                "user_id": owner,
                "conversation_id": thread,
                "transport_run_id": run_id,
            }

        lease = await worker_a.admit(
            **identity(), request_id="request-a", correlation_id="trace-a",
        )
        assert lease is not None
        assert await worker_b.admit(
            **identity(), request_id="replay", correlation_id="replay",
        ) is None
        assert await worker_b.request_cancel(**identity(
            owner=user_b, tenant=tenant_b,
        )) is None
        assert await worker_a.renew(lease)
        assert await worker_b.request_cancel(**identity()) == "cancelling"
        # A second independent repository instance reads the actual committed
        # SQL state, not a process-local boolean or an SDK transport guess.
        assert await worker_b.read_status(**identity()) == {
            "status": "cancelling",
            "cancel_requested": True,
            "cancellation_confirmed": False,
        }
        assert await worker_b.read_status(**identity(
            owner=user_b, tenant=tenant_b,
        )) is None
        assert await worker_b.request_cancel(**identity()) == "cancelling"
        assert not await worker_a.renew(lease)
        assert await worker_a.cancel_requested(lease)
        with pytest.raises(ValueError, match="requires_atomic_transcript_commit"):
            await worker_a.finish(lease, status="completed")
        assert await worker_a.finish(
            lease, status="cancelled", error_code="CHAT_STREAM_CANCELLED",
        )
        assert await worker_b.request_cancel(**identity()) == "cancelled"
        assert await worker_b.read_status(**identity()) == {
            "status": "cancelled",
            "cancel_requested": True,
            "cancellation_confirmed": True,
        }
        assert await worker_a.read_status(**identity(
            run_id="run-does-not-exist",
        )) is None
        assert not await worker_b.finish(lease, status="cancelled")

        # Simultaneous stop/completion on two independent connections:
        # serialized SQL transitions must produce exactly one final state.
        race_lease = await worker_a.admit(
            **identity(run_id="run-race"),
            request_id="race-a", correlation_id="race-trace",
        )
        assert race_lease is not None
        def message(role: str) -> Message:
            return Message(
                id=str(uuid.uuid4()),
                conversation_id=thread,
                tenant_id=tenant_a,
                role=role,
                content="A literal test message" if role == "user" else "Authorized reply",
                metadata={
                    "authorized_user_id": user_a,
                    "request_id": race_lease.request_id,
                    "correlation_id": race_lease.correlation_id,
                },
            )
        user_message = message("user")
        assistant_message = message("assistant")
        stop_result, transcript_result = await asyncio.gather(
            worker_b.request_cancel(**identity(run_id="run-race")),
            conversations.add_completed_turn(
                user_message, assistant_message, run_lease=race_lease,
            ),
        )
        if transcript_result.success:
            assert transcript_result.data == 2
            assert stop_result == "completed"
            bound_ids = await raw.fetchrow(
                """
                SELECT user_message_id, assistant_message_id, assistant_message_digest
                FROM public.runtime_chat_runs
                WHERE execution_id=$1 AND status='completed'
                """,
                uuid.UUID(race_lease.execution_id),
            )
            assert bound_ids is not None
            assert bound_ids["user_message_id"] == uuid.UUID(user_message.id)
            assert bound_ids["assistant_message_id"] == uuid.UUID(assistant_message.id)
            assert bound_ids["assistant_message_digest"] == canonical_message_digest(
                assistant_message
            )
            replay_proof = await worker_b.completed_replay_attestations(
                tenant_id=tenant_a, user_id=user_a, conversation_id=thread,
            )
            assert replay_proof.get(assistant_message.id) == (
                race_lease.request_id, canonical_message_digest(assistant_message),
            )
            assert await worker_a.committed_turn(
                race_lease,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
            )
        else:
            assert stop_result == "cancelling"
            assert await worker_a.cancel_requested(race_lease)
            assert await worker_a.finish(
                race_lease, status="cancelled",
                error_code="CHAT_STREAM_CANCELLED",
            )
            assert not await worker_a.committed_turn(
                race_lease,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
            )
        stored_count = await raw.fetchval(
            """
            SELECT COUNT(*) FROM public.messages
            WHERE message_id = ANY($1::uuid[])
            """,
            [uuid.UUID(user_message.id), uuid.UUID(assistant_message.id)],
        )
        assert stored_count == (2 if transcript_result.success else 0)
        observed = await raw.fetchval(
            """
            SELECT status FROM public.runtime_chat_runs
            WHERE execution_id=$1
            """,
            uuid.UUID(race_lease.execution_id),
        )
        assert observed in {"completed", "cancelled"}
        race_status = await worker_b.read_status(**identity(run_id="run-race"))
        assert race_status == {
            "status": observed,
            "cancel_requested": observed == "cancelled",
            "cancellation_confirmed": observed == "cancelled",
        }

        # Event cursor persisted by one worker is readable by another.
        journal = await worker_a.admit(
            **identity(run_id="run-journal"),
            request_id="journal-a", correlation_id="journal-trace",
        )
        assert journal is not None
        assert await worker_a.append_projected_event(journal, event={
            "type": "RUN_STARTED",
            "threadId": thread,
            "runId": "run-journal",
        }) == 1
        assert await worker_a.append_projected_event(journal, event={
            "type": "TEXT_MESSAGE_CONTENT",
            "messageId": "assistant-run-journal",
            "delta": "This was actually observed.",
        }) == 2
        other_worker_page = await worker_b.read_projected_events(
            **identity(run_id="run-journal"), after=0, limit=1,
        )
        assert other_worker_page is not None
        assert other_worker_page["nextCursor"] == 1
        assert other_worker_page["hasMore"] is True
        assert other_worker_page["runStatus"] == "running"
        assert other_worker_page["continuationAvailable"] is False
        second_page = await worker_b.read_projected_events(
            **identity(run_id="run-journal"), after=1, limit=1,
        )
        assert second_page["nextCursor"] == 2
        assert second_page["events"][0]["event"]["delta"] == (
            "This was actually observed."
        )
        assert await worker_b.read_projected_events(
            **identity(tenant=tenant_b, owner=user_b, run_id="run-journal"),
        ) is None
        assert await worker_b.request_cancel(
            **identity(run_id="run-journal")
        ) == "cancelling"
        with pytest.raises(ValueError, match="chat_projection_run_not_active"):
            await worker_a.append_projected_event(journal, event={
                "type": "TEXT_MESSAGE_CONTENT", "messageId": "assistant-run-journal",
                "delta": "Unowned after stop.",
            })
        assert await worker_a.finish(
            journal, status="cancelled", error_code="CHAT_STREAM_CANCELLED",
        )
        assert await worker_a.append_projected_event(journal, event={
            "type": "RUN_ERROR",
            "message": "This chat run was cancelled.",
            "code": "CHAT_STREAM_CANCELLED",
        }) == 3
        terminal_page = await worker_b.read_projected_events(
            **identity(run_id="run-journal"), after=2, limit=10,
        )
        assert terminal_page["runStatus"] == "cancelled"
        assert terminal_page["terminalConfirmed"] is True
        assert terminal_page["continuationAvailable"] is False
        assert terminal_page["events"][0]["event"]["type"] == "RUN_ERROR"

        # CK-07E6: real PostgreSQL compare-and-swap proof for two windows,
        # tenant/user scope, and parent-conversation erasure (migration 47).
        draft_thread = str(uuid.uuid4())
        await raw.execute(
            "INSERT INTO public.conversations(conversation_id,tenant_id,user_id) "
            "VALUES ($1,$2,$3)",
            uuid.UUID(draft_thread), uuid.UUID(tenant_a), uuid.UUID(user_a),
        )
        empty = await conversations.get_composer_draft(
            draft_thread, tenant_a, user_id=user_a,
        )
        assert empty.success and empty.data == {"text": "", "revision": 0}
        first = await conversations.put_composer_draft(
            draft_thread, tenant_a, user_id=user_a,
            content="Unsent across windows", expected_revision=0,
        )
        assert first.success and first.data == {
            "text": "Unsent across windows", "revision": 1,
        }
        assert (await conversations.get_composer_draft(
            draft_thread, tenant_a, user_id=user_a,
        )).data == first.data
        stale = await conversations.put_composer_draft(
            draft_thread, tenant_a, user_id=user_a,
            content="Stale tab must not overwrite", expected_revision=0,
        )
        assert not stale.success
        assert stale.error == "composer_draft_revision_conflict"
        second = await conversations.put_composer_draft(
            draft_thread, tenant_a, user_id=user_a,
            content="Newer draft", expected_revision=1,
        )
        assert second.success and second.data["revision"] == 2
        foreign = await conversations.get_composer_draft(
            draft_thread, tenant_b, user_id=user_b,
        )
        assert not foreign.success and foreign.error == "conversation_not_found"
        foreign_write = await conversations.put_composer_draft(
            draft_thread, tenant_b, user_id=user_b,
            content="Cross tenant", expected_revision=2,
        )
        assert not foreign_write.success
        assert foreign_write.error == "conversation_not_found"
        assert (await conversations.get_composer_draft(
            draft_thread, tenant_a, user_id=user_a,
        )).data["text"] == "Newer draft"

        # Actual PostgreSQL RLS must hold for a least-privilege login;
        # superuser-only repository queries do not prove policy isolation.
        await raw.execute(
            "CREATE ROLE karen_ci_chat_reader LOGIN PASSWORD 'chat_cursor_ci_only'"
        )
        await raw.execute(
            "GRANT CONNECT ON DATABASE karen_chat_run_test TO karen_ci_chat_reader"
        )
        await raw.execute(
            "GRANT USAGE ON SCHEMA public TO karen_ci_chat_reader"
        )
        await raw.execute(
            "GRANT SELECT ON public.runtime_chat_runs, "
            "public.runtime_chat_run_events, public.conversation_composer_drafts, "
            "public.conversations TO karen_ci_chat_reader"
        )
        reader = await asyncpg.connect(
            "postgresql://karen_ci_chat_reader:chat_cursor_ci_only@"
            "127.0.0.1:5432/karen_chat_run_test"
        )
        try:
            assert await reader.fetchval(
                "SELECT count(*) FROM public.runtime_chat_run_events"
            ) == 0
            async with reader.transaction():
                await reader.execute(
                    "SELECT set_config('app.current_tenant_id', $1, true)",
                    tenant_a,
                )
                await reader.execute(
                    "SELECT set_config('app.current_user_id', $1, true)",
                    user_a,
                )
                assert await reader.fetchval(
                    "SELECT count(*) FROM public.runtime_chat_run_events"
                ) == 3
                assert await reader.fetchval(
                    "SELECT draft_text FROM public.conversation_composer_drafts "
                    "WHERE conversation_id=$1", uuid.UUID(draft_thread),
                ) == "Newer draft"
                assert await reader.fetchval(
                    "SELECT count(*) FROM public.runtime_chat_runs "
                    "WHERE transport_run_id='run-journal'"
                ) == 1
            async with reader.transaction():
                await reader.execute(
                    "SELECT set_config('app.current_tenant_id', $1, true)",
                    tenant_b,
                )
                await reader.execute(
                    "SELECT set_config('app.current_user_id', $1, true)",
                    user_b,
                )
                assert await reader.fetchval(
                    "SELECT count(*) FROM public.runtime_chat_run_events"
                ) == 0
                assert await reader.fetchval(
                    "SELECT count(*) FROM public.conversation_composer_drafts"
                ) == 0
                assert await reader.fetchval(
                    "SELECT count(*) FROM public.runtime_chat_runs "
                    "WHERE transport_run_id='run-journal'"
                ) == 0
        finally:
            await reader.close()

        deleted_draft_parent = await conversations.delete_conversation(
            draft_thread, tenant_a, user_id=user_a,
        )
        assert deleted_draft_parent.success and deleted_draft_parent.data
        assert await raw.fetchval(
            "SELECT count(*) FROM public.conversation_composer_drafts "
            "WHERE conversation_id=$1", uuid.UUID(draft_thread),
        ) == 0
        assert not (await conversations.get_composer_draft(
            draft_thread, tenant_a, user_id=user_a,
        )).success

        expired = await worker_a.admit(
            **identity(run_id="run-expired"),
            request_id="expired-a", correlation_id="expired-trace",
        )
        assert expired is not None
        await raw.execute(
            """
            UPDATE public.runtime_chat_runs
            SET lease_expires_at = NOW() - INTERVAL '1 second'
            WHERE execution_id = $1
            """,
            uuid.UUID(expired.execution_id),
        )
        # An expired lease must be an interruption, never a terminal
        # cancellation confirmation, even before an operator asks to stop.
        assert await worker_b.read_status(**identity(run_id="run-expired")) == {
            "status": "interrupted",
            "cancel_requested": False,
            "cancellation_confirmed": False,
        }
        assert await worker_b.request_cancel(
            **identity(run_id="run-expired")
        ) == "orphaned"
        assert await worker_b.read_status(**identity(run_id="run-expired")) == {
            "status": "orphaned",
            "cancel_requested": False,
            "cancellation_confirmed": False,
        }
        assert not await worker_a.finish(expired, status="cancelled")
        assert not await worker_a.cancel_requested(expired)

        # RLS and explicit query scoping are both present; a separate
        # tenant may have the same transport run ID, but cannot touch ours.
        b_thread = str(uuid.uuid4())
        distinct = await worker_b.admit(
            tenant_id=tenant_b, user_id=user_b,
            conversation_id=b_thread, transport_run_id="run-one",
            request_id="other", correlation_id="other",
        )
        assert distinct is not None
        assert await worker_b.request_cancel(**identity(
            owner=user_b, tenant=tenant_b, run_id="run-one",
        )) is None
        assert await worker_b.finish(distinct, status="failed",
                                    error_code="CHAT_TEST_TERMINAL")

    finally:
        if engine is not None:
            await engine.dispose()
        await raw.close()
