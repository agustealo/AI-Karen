"""Real PostgreSQL draft CAS and artifact ownership proof on disposable CI DB."""
from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_karen_engine.auth import auth_service
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.services.auth.auth_service import AuthService
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.contracts import ExecutionBudgetMeter
from ai_karen_engine.core.runtime.policy.runtime_policy import (
    PolicyEvaluationRequest,
    RuntimePolicyEnforcer,
)
from ai_karen_engine.persistence.repositories import chat_run_repository
from ai_karen_engine.services.database.repositories.conversation_repository import (
    Message,
    canonical_message_digest,
    draft_attachment_selection_digest,
)
from ai_karen_engine.services.database.repositories.postgres_conversation_repository import (
    PostgresConversationRepository,
)


@pytest.mark.asyncio
async def test_attachment_draft_atomic_cas_and_owner_scope(monkeypatch):
    if os.getenv("KAREN_TEST_DISPOSABLE_DATABASE") != "1":
        pytest.skip("Requires explicit disposable PostgreSQL opt-in")
    dsn = os.environ["CHAT_TEST_DATABASE_URL"]
    parsed = urlparse(dsn)
    if (
        parsed.scheme != "postgresql+asyncpg"
        or parsed.hostname not in ("127.0.0.1", "localhost")
        or parsed.port != 5432
        or parsed.path != "/ai_karen"
    ):
        raise ValueError("Refusing non-disposable database")
    # Separate database within the disposable CI cluster; no existing tables
    # are dropped or replaced, and the actual draft migrations are applied.
    db_name = "draft_proof_" + uuid4().hex
    admin = create_async_engine(dsn, isolation_level="AUTOCOMMIT")
    engine = None
    created = False
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        created = True
        from sqlalchemy.engine import make_url
        engine = create_async_engine(make_url(dsn).set(database=db_name))
        root = Path(__file__).resolve().parents[2]
        migrations = root / "supabase/migrations"
        async with engine.begin() as conn:
            for sql in (
                "CREATE TABLE public.tenants (id uuid PRIMARY KEY)",
                "CREATE TABLE public.auth_users (user_id uuid PRIMARY KEY)",
                """CREATE TABLE public.conversations (
                    conversation_id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
                    user_id uuid NOT NULL,
                    conversation_metadata jsonb NOT NULL DEFAULT '{}'::jsonb
                )""",
                """CREATE TABLE public.messages (
                    message_id uuid PRIMARY KEY,
                    conversation_id uuid NOT NULL REFERENCES public.conversations(conversation_id),
                    role text NOT NULL, content text NOT NULL,
                    message_metadata jsonb NOT NULL, created_at timestamptz NOT NULL
                )""",
                """CREATE TABLE public.files (
                    file_id text PRIMARY KEY, tenant_id text NOT NULL,
                    owner_user_id uuid NOT NULL, sha256 text NOT NULL,
                    deleted_at timestamp
                )""",
            ):
                await conn.execute(text(sql))
        # Execute migration scripts through asyncpg because each contains
        # multiple SQL statements and its own transaction boundary.
        async with engine.connect() as conn:
            raw = await conn.get_raw_connection()
            for name in (
                "20261026010000_47_conversation_composer_drafts.sql",
                "20261124010000_73_composer_draft_attachment_references.sql",
                "20261025020000_43_runtime_chat_run_ledger.sql",
                "20261025030000_44_runtime_chat_replay_identity.sql",
                "20261025040000_45_runtime_chat_replay_digest.sql",
                "20261125010000_74_runtime_chat_single_active_run.sql",
                "20261125020000_75_runtime_chat_submission_identity.sql",
                "20261125030000_76_runtime_chat_unresolved_run.sql",
            ):
                await raw.driver_connection.execute(
                    (migrations / name).read_text(encoding="utf-8")
                )
        tenant, other_tenant, owner, other_owner, conversation = [
            str(uuid4()) for _ in range(5)
        ]
        source, foreign, archived, cross_tenant = [str(uuid4()) for _ in range(4)]
        digest = "a" * 64
        ref = {"source_id": source, "revision": digest}
        async with engine.begin() as conn:
            for tid in (tenant, other_tenant):
                await conn.execute(text("INSERT INTO tenants VALUES (CAST(:id AS uuid))"), {"id": tid})
            for uid in (owner, other_owner):
                await conn.execute(text("INSERT INTO auth_users VALUES (CAST(:id AS uuid))"), {"id": uid})
            await conn.execute(text(
                "INSERT INTO conversations (conversation_id, tenant_id, user_id) VALUES (CAST(:c AS uuid), CAST(:t AS uuid), CAST(:u AS uuid))"
            ), {"c": conversation, "t": tenant, "u": owner})
            for sid, tid, uid in (
                (source, tenant, owner), (foreign, tenant, other_owner),
                (archived, tenant, owner), (cross_tenant, other_tenant, owner),
            ):
                await conn.execute(text(
                    "INSERT INTO files VALUES (:s, :t, CAST(:u AS uuid), :d, NULL)"
                ), {"s": sid, "t": tid, "u": uid, "d": digest})
            await conn.execute(text("UPDATE files SET deleted_at = NOW() WHERE file_id = :s"), {"s": archived})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        repo = PostgresConversationRepository(factory)

        @asynccontextmanager
        async def real_scope(tenant_id, *, user_id):
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

        monkeypatch.setattr(chat_run_repository, "async_transaction_scope", real_scope)
        monkeypatch.setattr(
            chat_run_repository.SqlChatRunRepository, "_attention_enabled",
            staticmethod(lambda: False),
        )
        runs = chat_run_repository.SqlChatRunRepository()

        async def admit(run_id, revision, refs, content="draft", *, principal=owner):
            return await runs.admit(
                tenant_id=tenant, user_id=principal, conversation_id=conversation,
                transport_run_id=run_id, request_id=run_id, correlation_id=run_id,
                submission_id=f"draft-v2-{revision}-" + draft_attachment_selection_digest(refs),
                submitted_text=content, submitted_attachment_references=refs,
            )

        async def count_runs(run_id, *, principal=owner):
            async with real_scope(tenant, user_id=principal) as session:
                return (await session.execute(
                    text("SELECT count(*) FROM public.runtime_chat_runs WHERE transport_run_id = :run"),
                    {"run": run_id},
                )).scalar_one()

        async def write(revision, refs, content="draft"):
            return await repo.put_composer_draft_with_attachments(
                conversation, tenant, user_id=owner, content=content,
                expected_revision=revision, attachment_references=refs,
            )

        initial = await repo.get_composer_draft_with_attachments(conversation, tenant, user_id=owner)
        assert initial.success and initial.data == {"text": "", "revision": 0, "attachment_references": []}
        for sid in (foreign, archived, cross_tenant, str(uuid4())):
            denied = await write(0, [{"source_id": sid, "revision": digest}])
            assert not denied.success and denied.error == "composer_attachment_unavailable"
        assert not (await write(0, [{**ref, "revision": "b" * 64}])).success
        assert not (await write(0, [ref, ref])).success
        saved = await write(0, [ref])
        assert saved.success and saved.data == {"text": "draft", "revision": 1, "attachment_references": [ref]}
        # A persisted selection is not an admitted chat run. Until the
        # attachment-aware execution contract is wired, even the exact
        # submitted revision and text must fail the text-only run fence.
        async with async_sessionmaker(engine)() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant},
                )
                await session.execute(
                    text("SELECT set_config('app.current_user_id', :owner, true)"),
                    {"owner": owner},
                )
                assert not await repo.lock_matching_submission_draft(
                    session, tenant_id=tenant, user_id=owner,
                    conversation_id=conversation, revision=1, submitted_text="draft",
                )
        # Use a digest that matches the submitted hints but not the persisted
        # selection, so the actual SQL lock (not the hash check) rejects it.
        for run_id, revision, refs, content, principal in (
            ("substitution", 1, [{**ref, "revision": "b" * 64}], "draft", owner),
            ("stale", 2, [ref], "draft", owner),
            ("wrong-text", 1, [ref], "different", owner),
            ("foreign-owner", 1, [ref], "draft", other_owner),
        ):
            with pytest.raises(chat_run_repository.DraftSubmissionConflict):
                await admit(run_id, revision, refs, content, principal=principal)
            assert await count_runs(run_id, principal=principal) == 0

        lease = await admit("first", 1, [ref])
        assert lease is not None
        assert await count_runs("first") == 1
        assert await admit("duplicate", 1, [ref]) is None
        assert await runs.finish(lease, status="failed", error_code="CHAT_TEST_TERMINAL")
        assert await admit("failed-replay", 1, [ref]) is None
        assert await count_runs("failed-replay") == 0
        retained = await repo.get_composer_draft_with_attachments(
            conversation, tenant, user_id=owner,
        )
        assert retained.success and retained.data == saved.data
        assert not (await repo.get_composer_draft(conversation, tenant, user_id=owner)).success
        assert not (await repo.put_composer_draft(
            conversation, tenant, user_id=owner, content="legacy", expected_revision=1,
        )).success
        assert not (await repo.get_composer_draft_with_attachments(conversation, tenant, user_id=other_owner)).success
        assert not (await repo.get_composer_draft_with_attachments(conversation, other_tenant, user_id=owner)).success
        assert not (await write(0, [], "stale")).success
        results = await asyncio.gather(write(1, [ref], "left"), write(1, [ref], "right"))
        assert sum(result.success for result in results) == 1
        current = await repo.get_composer_draft_with_attachments(conversation, tenant, user_id=owner)
        assert current.success and current.data["revision"] == 2
        assert current.data["attachment_references"] == [ref]
        assert current.data["text"] in {"left", "right"}
        in_flight = await admit("second", 2, [ref], current.data["text"])
        assert in_flight is not None
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE files SET deleted_at = NOW() WHERE file_id = :s"), {"s": source})
        assert not (await write(2, [ref])).success
        cleared = await write(2, [], "cleared")
        assert cleared.success and cleared.data["revision"] == 3
        # A newer CAS edit while the admitted run is live must survive stop.
        assert await runs.finish(in_flight, status="cancelled")
        assert await admit("cancelled-replay", 2, [ref], current.data["text"]) is None
        assert (await repo.get_composer_draft_with_attachments(
            conversation, tenant, user_id=owner,
        )).data == cleared.data
        legacy = await repo.get_composer_draft(conversation, tenant, user_id=owner)
        assert legacy.success and legacy.data == {"text": "cleared", "revision": 3}
        # Removing the selection through the canonical CAS makes only the
        # new text-only revision eligible; the previously attached revision
        # cannot be replayed as an ordinary chat submission.
        async with async_sessionmaker(engine)() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant},
                )
                await session.execute(
                    text("SELECT set_config('app.current_user_id', :owner, true)"),
                    {"owner": owner},
                )
                for revision, submitted_text, expected in (
                    (1, "draft", False),
                    (2, current.data["text"], False),
                    # Matching current text isolates the stale revision fence.
                    (1, "cleared", False),
                    (2, "cleared", False),
                    (3, "different text", False),
                    (3, "cleared", True),
                ):
                    assert await repo.lock_matching_submission_draft(
                        session, tenant_id=tenant, user_id=owner,
                        conversation_id=conversation, revision=revision,
                        submitted_text=submitted_text,
                    ) is expected

        # Completion proof: real PostgreSQL transactions, actual context/policy
        # and issuer binding, with controlled account and verified text fixtures.
        # No live authentication, Storage download or model inference is claimed.
        body = "Controlled private document."
        active_ref = {
            "source_id": str(uuid4()),
            "revision": hashlib.sha256(body.encode()).hexdigest(),
        }
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO files VALUES (:s, :t, CAST(:u AS uuid), :d, NULL)"
            ), {"s": active_ref["source_id"], "t": tenant, "u": owner, "d": active_ref["revision"]})
        issuer = object.__new__(AuthService)
        issuer._runtime_witness_key = secrets.token_bytes(32)
        account = SimpleNamespace(
            id=owner, tenant_id=tenant, status="active", is_verified=True, roles=["admin"],
        )
        issuer.revalidate_session_identity = AsyncMock(return_value=account)
        issuer.revalidate_issued_session_in_transaction = AsyncMock(return_value=account)
        monkeypatch.setattr(auth_service, "get_auth_service", AsyncMock(return_value=issuer))

        async def private_context(run):
            ctx = ChatExecutionContext(
                user_id=owner, tenant_id=tenant, conversation_id=conversation,
                session_id="completion-proof", request_id=run.request_id,
                correlation_id=run.correlation_id,
                authenticated_user=UserData(
                    user_id=owner, tenant_id=tenant, is_active=True, is_verified=True,
                    permissions=["data:read"],
                ),
            )
            principal = ctx.authenticated_user
            witness = issuer._issue_session_witness(
                session_id=str(uuid4()), user_id=owner, tenant_id=tenant,
                access_token_digest="a" * 64,
            )
            assert issuer.bind_issued_session_principal(witness, principal)
            principal._runtime_session_witness = (principal, witness)
            policy = RuntimePolicyEnforcer()
            decision = await policy.evaluate(PolicyEvaluationRequest(
                user_id=owner, tenant_id=tenant, session_id=ctx.session_id,
                correlation_id=ctx.correlation_id, action="general_assist",
                permissions=["data:read"], requested_capabilities=["data:read"],
                attachment_references=[active_ref], max_model_calls=2,
            ))
            assert decision.allowed
            policy.bind_chat_model_policy(context=ctx, decision=decision)
            plan = decision.to_authorized_plan()
            plan.resource_scope["attachment_references"] = [
                dict(item) for item in decision.runtime_constraints["attachment_references"]
            ]
            meter = ExecutionBudgetMeter(plan.budget)
            ctx.bind_runtime_model_authority(plan, meter)
            meter.start()
            ctx.bind_runtime_attachment_scope(plan, meter, [active_ref])
            await ctx.revalidate_runtime_attachment_session()
            ctx.bind_runtime_attachment_documents(
                plan, meter, [{**active_ref, "text": body}],
            )
            return ctx

        def pair(run, content):
            return [
                Message(
                    id=str(uuid4()), conversation_id=conversation, tenant_id=tenant,
                    role=role, content=value, metadata={
                        "source": "chat_runtime", "transcript_actor": role,
                        "authorized_user_id": owner, "request_id": run.request_id,
                        "correlation_id": run.correlation_id,
                        "session_id": "completion-proof", "conversation_id": conversation,
                    },
                )
                for role, value in (("user", content), ("assistant", "Controlled response"))
            ]

        async def readback(run, ctx, messages):
            return await repo.read_committed_turn(
                conversation_id=conversation, tenant_id=tenant, user_id=owner,
                request_id=run.request_id, correlation_id=run.correlation_id,
                session_id=ctx.session_id, user_message_id=messages[0].id,
                assistant_message_id=messages[1].id, user_text=messages[0].content,
                assistant_text=messages[1].content, private_execution=ctx, run_lease=run,
                expected_assistant_digest=canonical_message_digest(messages[1]),
            )

        async def observe(run):
            async with real_scope(tenant, user_id=owner) as session:
                status = (await session.execute(text(
                    "SELECT status FROM public.runtime_chat_runs WHERE execution_id = CAST(:id AS uuid)"
                ), {"id": run.execution_id})).scalar_one()
                count = (await session.execute(text(
                    "SELECT count(*) FROM public.messages WHERE message_metadata->>'request_id' = :req"
                ), {"req": run.request_id})).scalar_one()
                return status, count

        attached = await write(3, [active_ref], "Complete attached draft")
        assert attached.success and attached.data["revision"] == 4
        completing = await admit("complete-private", 4, [active_ref], attached.data["text"])
        assert completing is not None
        ctx = await private_context(completing)
        messages = pair(completing, attached.data["text"])
        # Refusal without the private context cannot change any of the three stores.
        denied = await repo.add_completed_turn(*messages, run_lease=completing)
        assert not denied.success and denied.error == "attachment_session_denied"
        assert await observe(completing) == ("running", 0)
        assert (await repo.get_composer_draft_with_attachments(
            conversation, tenant, user_id=owner,
        )).data == attached.data

        # A real database error during retirement must roll back BOTH messages
        # and the already-staged terminal UPDATE, not just the draft change.
        async with engine.begin() as conn:
            await conn.execute(text("""
                CREATE FUNCTION reject_draft_retirement() RETURNS trigger LANGUAGE plpgsql AS $
                BEGIN RAISE EXCEPTION 'controlled retirement failure'; END;
                $
            """))
            await conn.execute(text("""
                CREATE TRIGGER reject_retirement BEFORE UPDATE ON public.conversation_composer_drafts
                FOR EACH ROW WHEN (NEW.draft_text = '' AND OLD.draft_text <> '')
                EXECUTE FUNCTION reject_draft_retirement()
            """))
        failed = await repo.add_completed_turn(
            *messages, run_lease=completing, private_execution=ctx,
        )
        assert not failed.success and failed.error == "completed_turn_write_failed"
        assert failed.metadata["commit_outcome_uncertain"] is False
        assert await observe(completing) == ("running", 0)
        assert (await repo.get_composer_draft_with_attachments(
            conversation, tenant, user_id=owner,
        )).data == attached.data
        assert not (await readback(completing, ctx, messages)).success
        async with engine.begin() as conn:
            await conn.execute(text("DROP TRIGGER reject_retirement ON public.conversation_composer_drafts"))

        # Inject an exception after the real commit, not a fabricated receipt.
        class LostCommitReceiptSession(AsyncSession):
            async def __aexit__(self, exc_type, exc_value, traceback):
                await super().__aexit__(exc_type, exc_value, traceback)
                if exc_type is None:
                    raise RuntimeError("controlled post-commit receipt loss")

        lost_repo = PostgresConversationRepository(async_sessionmaker(
            engine, class_=LostCommitReceiptSession, expire_on_commit=False,
        ))
        uncertain = await lost_repo.add_completed_turn(
            *messages, run_lease=completing, private_execution=ctx,
        )
        assert not uncertain.success and uncertain.error == "completed_turn_write_failed"
        assert uncertain.metadata["commit_outcome_uncertain"] is True
        assert await observe(completing) == ("completed", 2)
        recovered = await readback(completing, ctx, messages)
        assert recovered.success and recovered.data is True
        retired = await repo.get_composer_draft_with_attachments(
            conversation, tenant, user_id=owner,
        )
        assert retired.success and retired.data == {
            "text": "", "revision": 5, "attachment_references": [],
        }
        assert await admit("completion-replay", 4, [active_ref], attached.data["text"]) is None
        assert await observe(completing) == ("completed", 2)

        # An older successful private execution must not retire a newer draft.
        original = await write(5, [active_ref], "Original private question")
        assert original.success and original.data["revision"] == 6
        older = await admit("older-completion", 6, [active_ref], original.data["text"])
        assert older is not None
        older_ctx = await private_context(older)
        newer = await write(6, [active_ref], "Newer private question")
        assert newer.success and newer.data["revision"] == 7
        older_messages = pair(older, original.data["text"])
        completed = await repo.add_completed_turn(
            *older_messages, run_lease=older, private_execution=older_ctx,
        )
        assert completed.success and completed.data == 2
        assert await observe(older) == ("completed", 2)
        assert (await repo.get_composer_draft_with_attachments(
            conversation, tenant, user_id=owner,
        )).data == newer.data

        cancelled = await admit("cancel-before-completion", 7, [active_ref], newer.data["text"])
        assert cancelled is not None
        cancelled_ctx = await private_context(cancelled)
        assert await runs.finish(cancelled, status="cancelled")
        denied = await repo.add_completed_turn(
            *pair(cancelled, newer.data["text"]),
            run_lease=cancelled, private_execution=cancelled_ctx,
        )
        assert not denied.success and denied.error == "chat_run_commit_not_authorized"
        assert await observe(cancelled) == ("cancelled", 0)
        assert (await repo.get_composer_draft_with_attachments(
            conversation, tenant, user_id=owner,
        )).data == newer.data
        assert issuer.revalidate_issued_session_in_transaction.await_count >= 5
        for call in issuer.revalidate_issued_session_in_transaction.await_args_list:
            assert isinstance(call.args[3], AsyncSession)
    finally:
        if engine is not None:
            await engine.dispose()
        try:
            if created:
                async with admin.connect() as conn:
                    await conn.execute(text(f'DROP DATABASE "{db_name}"'))
        finally:
            await admin.dispose()
