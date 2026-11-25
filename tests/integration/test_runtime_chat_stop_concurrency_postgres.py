"""Real PostgreSQL proof for CK-07B, on a dedicated disposable database only.

Set CHAT_RUN_TEST_DATABASE_URL with database name EXACTLY karen_chat_run_test.
The test recreates the canonical run ledger in that dedicated database.
No production database is ever accepted.
"""

from __future__ import annotations

import asyncio
import os
import sys
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
from ai_karen_engine.core.runtime import chat_run_lifecycle
from ai_karen_engine.core.runtime.chat_run_lifecycle import (
    ChatRunCancellationRequested, ChatRunCoordinator,
)
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatStreamChunk, ChatStreamEventType,
)
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
                user_id uuid NOT NULL REFERENCES public.auth_users(user_id),
                conversation_metadata jsonb NOT NULL DEFAULT '{}'::jsonb
            );
            CREATE TABLE public.messages (
                message_id uuid PRIMARY KEY,
                conversation_id uuid NOT NULL REFERENCES public.conversations(conversation_id) ON DELETE CASCADE,
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
        attachment_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261124010000_73_composer_draft_attachment_references.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(attachment_migration)
        active_run_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261125010000_74_runtime_chat_single_active_run.sql"
        ).read_text()
        await raw.execute(active_run_migration)
        submission_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261125020000_75_runtime_chat_submission_identity.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(submission_migration)
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

        # Two distinct run IDs on independent connections must not both
        # acquire execution authority. Identical run IDs remain permanently
        # fenced even after the winner has reached a terminal state.
        admissions = await asyncio.gather(
            worker_a.admit(
                **identity(run_id="tab-a"),
                request_id="tab-request-a", correlation_id="tab-trace-a",
            ),
            worker_b.admit(
                **identity(run_id="tab-b"),
                request_id="tab-request-b", correlation_id="tab-trace-b",
            ),
        )
        winners = [item for item in admissions if item is not None]
        assert len(winners) == 1
        winner = winners[0]
        assert await raw.fetchval(
            "SELECT count(*) FROM public.runtime_chat_runs "
            "WHERE tenant_id=$1 AND user_id=$2 AND conversation_id=$3 "
            "AND status IN ('running', 'cancelling')",
            uuid.UUID(tenant_a), uuid.UUID(user_a), uuid.UUID(thread),
        ) == 1
        assert await worker_b.admit(
            **identity(run_id="tab-third"),
            request_id="third", correlation_id="third",
        ) is None
        assert await worker_a.request_cancel(
            **identity(run_id=winner.transport_run_id),
        ) == "cancelling"
        assert await worker_b.admit(
            **identity(run_id="tab-while-cancelling"),
            request_id="while-cancelling", correlation_id="while-cancelling",
        ) is None
        assert await worker_a.finish(
            winner, status="cancelled", error_code="CHAT_STREAM_CANCELLED",
        )
        assert await worker_b.admit(
            **identity(run_id=winner.transport_run_id),
            request_id="repeat", correlation_id="repeat",
        ) is None

        # Sequential retry with a NEW transport ID must not run the same
        # original user submission after its first terminal execution.
        submitted = await worker_a.admit(
            **identity(run_id="submission-first"), request_id="submission-request",
            correlation_id="submission-trace", submission_id="user-turn-1",
        )
        assert submitted is not None
        assert await worker_b.read_recovery_run(
            tenant_id=tenant_a, user_id=user_a, conversation_id=thread,
        ) == {"runId": "submission-first", "submissionId": "user-turn-1", "status": "running"}
        assert await worker_b.read_recovery_run(
            tenant_id=tenant_b, user_id=user_b, conversation_id=thread,
        ) is None
        assert await worker_a.finish(
            submitted, status="failed", error_code="CHAT_TEST_TERMINAL",
        )
        assert await worker_b.read_recovery_run(
            tenant_id=tenant_a, user_id=user_a, conversation_id=thread,
        ) is None
        assert await worker_b.admit(
            **identity(run_id="submission-retry"), request_id="retry-request",
            correlation_id="retry-trace", submission_id="user-turn-1",
        ) is None
        distinct_submission = await worker_b.admit(
            **identity(run_id="submission-next"), request_id="next-request",
            correlation_id="next-trace", submission_id="user-turn-2",
        )
        assert distinct_submission is not None
        assert await worker_b.finish(
            distinct_submission, status="failed", error_code="CHAT_TEST_TERMINAL",
        )

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

        # CK-07F5: a separate OS process (not merely another Python object)
        # imports the SAME production repository, opens its OWN connection,
        # and commits a stop for an admitted run. The parent reads that
        # committed state without shared memory, IPC cancellation shortcuts
        # or a mock PostgreSQL backend. This is still not model-worker proof.
        process_lease = await worker_a.admit(
            **identity(run_id="run-external-process"),
            request_id="external-process-a",
            correlation_id="external-process-trace",
        )
        assert process_lease is not None
        assert await worker_b.read_status(**identity(
            run_id="run-external-process",
        )) == {
            "status": "running",
            "cancel_requested": False,
            "cancellation_confirmed": False,
        }
        # Run the ACTUAL canonical coordinator around a blocked test stream.
        # The separate OS process must cause its heartbeat to cancel the
        # upstream await, close the generator and write terminal PostgreSQL.
        # No model/provider service or runtime executor is fabricated.
        monkeypatch.setattr(chat_run_lifecycle, "_heartbeat_seconds", lambda: 0.02)
        upstream_closed = asyncio.Event()
        blocked = asyncio.Event()

        async def blocked_upstream():
            try:
                yield ChatStreamChunk(
                    type=ChatStreamEventType.CONTENT,
                    content="test partial chunk",
                    correlation_id=process_lease.correlation_id,
                )
                await blocked.wait()
                yield ChatStreamChunk(
                    type=ChatStreamEventType.COMPLETE,
                    content="",
                    correlation_id=process_lease.correlation_id,
                )
            finally:
                upstream_closed.set()

        active_stream = ChatRunCoordinator(worker_a).stream(
            blocked_upstream(), lease=process_lease,
        )
        first_chunk = await asyncio.wait_for(anext(active_stream), timeout=10)
        assert first_chunk.content == "test partial chunk"
        worker_environment = {
            **os.environ,
            "KAREN_CI_RUN_CHILD_PROBE": "1",
            "KAREN_CI_RUN_CHILD_TENANT_ID": tenant_a,
            "KAREN_CI_RUN_CHILD_USER_ID": user_a,
            "KAREN_CI_RUN_CHILD_CONVERSATION_ID": thread,
            "KAREN_CI_RUN_CHILD_TRANSPORT_ID": "run-external-process",
        }
        probe = await asyncio.create_subprocess_exec(
            sys.executable,
            str(Path(__file__).with_name("chat_run_external_stop_probe.py")),
            env=worker_environment,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(probe.wait(), timeout=30)
        except asyncio.TimeoutError as exc:
            probe.kill()
            await probe.wait()
            raise AssertionError(
                "Isolated cancellation worker did not finish in its bounded window"
            ) from exc
        assert probe.returncode == 0, (
            "Isolated cancellation worker did not commit an authenticated scoped stop"
        )
        assert await worker_a.read_status(**identity(
            run_id="run-external-process",
        )) == {
            "status": "cancelling",
            "cancel_requested": True,
            "cancellation_confirmed": False,
        }
        assert not await worker_a.renew(process_lease)
        assert await worker_a.cancel_requested(process_lease)

        async def consume_remaining():
            async for chunk in active_stream:
                # A stale worker must NEVER emit a completed model response.
                assert chunk.type != ChatStreamEventType.COMPLETE

        with pytest.raises(ChatRunCancellationRequested):
            await asyncio.wait_for(consume_remaining(), timeout=10)
        assert upstream_closed.is_set(), (
            "A remote stop must actually close the blocked upstream generator"
        )
        assert await worker_b.read_status(**identity(
            run_id="run-external-process",
        )) == {
            "status": "cancelled",
            "cancel_requested": True,
            "cancellation_confirmed": True,
        }

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

        # The revision-bound handoff keeps text durable until transcript commit.
        # A stale or mismatched submission must roll back the staged ledger row.
        draft_identity = {
            "tenant_id": tenant_a, "user_id": user_a, "conversation_id": draft_thread,
        }
        with pytest.raises(module.DraftSubmissionConflict):
            await worker_a.admit(
                **draft_identity, transport_run_id="draft-stale", request_id="draft-stale",
                correlation_id="draft-stale", submission_id="draft-v1-1",
                submitted_text="Unsent across windows",
            )
        assert await raw.fetchval(
            "SELECT count(*) FROM public.runtime_chat_runs WHERE transport_run_id='draft-stale'",
        ) == 0
        with pytest.raises(module.DraftSubmissionConflict):
            await worker_a.admit(
                **draft_identity, transport_run_id="draft-mismatch", request_id="draft-mismatch",
                correlation_id="draft-mismatch", submission_id="draft-v1-2",
                submitted_text="different text",
            )
        draft_lease = await worker_a.admit(
            **draft_identity, transport_run_id="draft-admitted", request_id="draft-request",
            correlation_id="draft-trace", submission_id="draft-v1-2",
            submitted_text="Newer draft",
        )
        assert draft_lease is not None
        assert (await conversations.get_composer_draft(
            draft_thread, tenant_a, user_id=user_a,
        )).data == {"text": "Newer draft", "revision": 2}
        # A failed run does not erase the only recoverable user content.
        assert await worker_a.finish(draft_lease, status="failed", error_code="CHAT_TEST_TERMINAL")
        assert (await conversations.get_composer_draft(
            draft_thread, tenant_a, user_id=user_a,
        )).data == {"text": "Newer draft", "revision": 2}
        # A new explicit edit creates the next submission revision.
        assert (await conversations.put_composer_draft(
            draft_thread, tenant_a, user_id=user_a,
            content="Complete this draft", expected_revision=2,
        )).success
        draft_lease = await worker_a.admit(
            **draft_identity, transport_run_id="draft-complete", request_id="draft-complete",
            correlation_id="draft-complete", submission_id="draft-v1-3",
            submitted_text="Complete this draft",
        )
        assert draft_lease is not None
        draft_messages = [
            Message(
                id=str(uuid.uuid4()), conversation_id=draft_thread,
                tenant_id=tenant_a, role=role, content=content,
                metadata={
                    "authorized_user_id": user_a,
                    "request_id": draft_lease.request_id,
                    "correlation_id": draft_lease.correlation_id,
                    "transcript_actor": role,
                },
            )
            for role, content in (("user", "Complete this draft"), ("assistant", "Done"))
        ]
        assert (await conversations.add_completed_turn(*draft_messages, run_lease=draft_lease)).success
        assert (await conversations.get_composer_draft(
            draft_thread, tenant_a, user_id=user_a,
        )).data == {"text": "", "revision": 4}

        # A repeatable-read recovery snapshot cannot mix an older ledger
        # state with a newer completion committed by another connection.
        snapshot_lease = await worker_a.admit(
            **draft_identity, transport_run_id="snapshot-race",
            request_id="snapshot-race", correlation_id="snapshot-race",
            submission_id="snapshot-original",
        )
        assert snapshot_lease is not None
        async with factory() as read_session:
            async with read_session.begin():
                await read_session.execute(text(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                ))
                await read_session.execute(text(
                    "SELECT set_config('app.current_tenant_id', :tenant, true)"
                ), {"tenant": tenant_a})
                await read_session.execute(text(
                    "SELECT set_config('app.current_user_id', :owner, true)"
                ), {"owner": user_a})
                first_recovery = await worker_a.read_recovery_run(
                    **draft_identity, db_session=read_session,
                )
                assert first_recovery == {
                    "runId": "snapshot-race", "submissionId": "snapshot-original",
                    "status": "running",
                }
                assert await worker_b.finish(
                    snapshot_lease, status="failed", error_code="CHAT_TEST_TERMINAL",
                )
                assert await worker_b.read_recovery_run(**draft_identity) is None
                assert await worker_a.read_recovery_run(
                    **draft_identity, db_session=read_session,
                ) == first_recovery
                assert await worker_a.completed_replay_attestations(
                    **draft_identity, db_session=read_session,
                )
        assert await worker_a.read_recovery_run(**draft_identity) is None

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
                # The owner must see the actual retired row, not a missing
                # row or the text from before the completed transcript.
                owned_draft = await reader.fetchrow(
                    "SELECT draft_text, revision FROM public.conversation_composer_drafts "
                    "WHERE conversation_id=$1", uuid.UUID(draft_thread),
                )
                assert owned_draft is not None
                assert dict(owned_draft) == {"draft_text": "", "revision": 4}
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

        # A newer edit from a separate repository must survive completion
        # of the previously admitted revision. A new transport ID does not
        # grant the original submission another execution.
        assert (await conversations.put_composer_draft(
            draft_thread, tenant_a, user_id=user_a,
            content="Original in-flight draft", expected_revision=4,
        )).success
        editing_lease = await worker_a.admit(
            **draft_identity, transport_run_id="draft-edit-race",
            request_id="draft-edit-race", correlation_id="draft-edit-race",
            submission_id="draft-v1-5", submitted_text="Original in-flight draft",
        )
        assert editing_lease is not None
        other_conversations = PostgresConversationRepository(factory)
        newer = await other_conversations.put_composer_draft(
            draft_thread, tenant_a, user_id=user_a,
            content="New unsent question", expected_revision=5,
        )
        assert newer.success and newer.data["revision"] == 6
        editing_messages = [
            Message(
                id=str(uuid.uuid4()), conversation_id=draft_thread,
                tenant_id=tenant_a, role=role, content=content,
                metadata={
                    "authorized_user_id": user_a,
                    "request_id": editing_lease.request_id,
                    "correlation_id": editing_lease.correlation_id,
                    "transcript_actor": role,
                },
            )
            for role, content in (("user", "Original in-flight draft"), ("assistant", "Done"))
        ]
        assert (await conversations.add_completed_turn(
            *editing_messages, run_lease=editing_lease,
        )).success
        assert (await other_conversations.get_composer_draft(
            draft_thread, tenant_a, user_id=user_a,
        )).data == {"text": "New unsent question", "revision": 6}
        assert await worker_b.admit(
            **draft_identity, transport_run_id="draft-edit-replay",
            request_id="draft-edit-replay", correlation_id="draft-edit-replay",
            submission_id="draft-v1-5", submitted_text="Original in-flight draft",
        ) is None

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
        assert await raw.fetchval(
            "SELECT count(*) FROM public.messages WHERE conversation_id=$1",
            uuid.UUID(draft_thread),
        ) == 0
        assert await raw.fetchval(
            "SELECT count(*) FROM public.runtime_chat_runs WHERE conversation_id=$1",
            uuid.UUID(draft_thread),
        ) == 0

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

        # KP-RED-03: two concurrent persona runs may claim an empty session
        # shell only once. Real PostgreSQL must serialize both on the parent.
        scoped_thread = str(uuid.uuid4())
        await raw.execute(
            "INSERT INTO public.conversations(conversation_id,tenant_id,user_id) "
            "VALUES($1,$2,$3)",
            uuid.UUID(scoped_thread), uuid.UUID(tenant_a), uuid.UUID(user_a),
        )

        async def claim_persona(persona_name: str):
            provenance = {
                "authorized_user_id": user_a,
                "persona_scope_id": persona_name,
                "request_id": "claim-" + persona_name,
            }
            pair = (
                Message(
                    id=str(uuid.uuid4()), conversation_id=scoped_thread,
                    tenant_id=tenant_a, role="user", content=persona_name,
                    metadata={**provenance, "transcript_actor": "user"},
                ),
                Message(
                    id=str(uuid.uuid4()), conversation_id=scoped_thread,
                    tenant_id=tenant_a, role="assistant", content="scoped",
                    metadata={**provenance, "transcript_actor": "assistant"},
                ),
            )
            return await conversations.add_completed_turn(*pair)

        troy, morgan = await asyncio.gather(
            claim_persona("Troy"), claim_persona("Morgan"),
        )
        assert sorted([troy.success, morgan.success]) == [False, True]
        winner = "Troy" if troy.success else "Morgan"
        assert await raw.fetchval(
            "SELECT conversation_metadata->>'persona_scope_id' "
            "FROM public.conversations WHERE conversation_id=$1",
            uuid.UUID(scoped_thread),
        ) == winner
        assert await raw.fetchval(
            "SELECT count(*) FROM public.messages WHERE conversation_id=$1",
            uuid.UUID(scoped_thread),
        ) == 2

        # A direct single-message write with no matching purpose cannot
        # bypass the parent-row scope, including during concurrent commits.
        disallowed = await conversations.add_message(Message(
            id=str(uuid.uuid4()), conversation_id=scoped_thread,
            tenant_id=tenant_a, role="user", content="unattributed",
            metadata={"authorized_user_id": user_a},
        ))
        assert not disallowed.success
        allowed = await conversations.add_message(Message(
            id=str(uuid.uuid4()), conversation_id=scoped_thread,
            tenant_id=tenant_a, role="user", content="authorized note",
            metadata={"authorized_user_id": user_a, "persona_scope_id": winner},
        ))
        assert allowed.success

    finally:
        if engine is not None:
            await engine.dispose()
        await raw.close()
