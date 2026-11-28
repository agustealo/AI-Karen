"""Real PostgreSQL draft CAS and artifact ownership proof on disposable CI DB."""
from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_karen_engine.auth import auth_service
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.services.auth.auth_service import AuthService
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext, ChatExecutionRequest
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    ConversationRuntimeGateway,
)
from ai_karen_engine.core.runtime.owned_history_projection import (
    UnreplayableHistory, project_owned_history,
)
from ai_karen_engine.services.response.response_contracts import ResponseContract
from ai_karen_engine.services.response.response_validator import ResponseValidator
from ai_karen_engine.core.runtime.contracts import ExecutionBudgetMeter
from ai_karen_engine.core.runtime.policy.runtime_policy import (
    PolicyEvaluationRequest,
    RuntimePolicyEnforcer,
)
from ai_karen_engine.persistence.repositories import chat_run_repository
from ai_karen_engine.services.database.repositories.artifact_store import VerifiedArtifactText
from ai_karen_engine.services.database.repositories.conversation_repository import (
    COMPLETED_ATTACHMENT_RECEIPT_KEY,
    Message,
    build_completed_attachment_receipt,
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
                    session_id text, title text, is_active boolean DEFAULT true,
                    summary text, tags text[] DEFAULT '{}',
                    created_at timestamptz DEFAULT NOW(), updated_at timestamptz DEFAULT NOW(),
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
                "20261128010000_79_runtime_chat_retry_receipt.sql",
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
                plan, meter, [VerifiedArtifactText(
                    artifact_id=active_ref["source_id"],
                    tenant_id=tenant,
                    user_id=owner,
                    filename="controlled.txt",
                    mime_type="text/plain",
                    sha256=active_ref["revision"],
                    text=body,
                )],
            )
            return ctx

        def pair(run, content):
            messages = [
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
            messages[1].metadata[COMPLETED_ATTACHMENT_RECEIPT_KEY] = (
                build_completed_attachment_receipt(messages[0], run.submission_id, [active_ref])
            )
            return messages

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

        # The caller cannot substitute a different historical receipt even with
        # an otherwise valid private execution and lease.
        receipt = messages[1].metadata.pop(COMPLETED_ATTACHMENT_RECEIPT_KEY)
        forged = await repo.add_completed_turn(
            *messages, run_lease=completing, private_execution=ctx,
        )
        assert not forged.success and forged.error == "attachment_session_denied"
        assert await observe(completing) == ("running", 0)
        messages[1].metadata[COMPLETED_ATTACHMENT_RECEIPT_KEY] = receipt

        # A real database error during retirement must roll back BOTH messages
        # and the already-staged terminal UPDATE, not just the draft change.
        async with engine.begin() as conn:
            # Sequences are not rolled back. This witness proves that the
            # injected fault was reached, not an unrelated earlier SQL error.
            await conn.execute(text("CREATE SEQUENCE retirement_fault_witness"))
            await conn.execute(text("""
                CREATE FUNCTION reject_draft_retirement() RETURNS trigger
                LANGUAGE plpgsql AS $retirement$
                BEGIN
                    PERFORM nextval('retirement_fault_witness');
                    RAISE EXCEPTION 'controlled retirement failure' USING ERRCODE = '23514';
                END;
                $retirement$
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
        assert failed.metadata["failure_class"] == "database_integrity_failure"
        async with engine.connect() as conn:
            witness = (await conn.execute(text(
                "SELECT last_value, is_called FROM retirement_fault_witness"
            ))).one()
            assert tuple(witness) == (1, True)
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
        attachment_gateway = ConversationRuntimeGateway(repository=repo)

        async def attached_history(*, text_only=False):
            snapshot = await attachment_gateway.get_owned_snapshot(ctx, message_limit=501)
            proofs = await runs.completed_replay_attestations(
                tenant_id=tenant, user_id=owner, conversation_id=conversation,
            )
            return project_owned_history(snapshot, attestations=proofs,
                                         text_continuation=text_only)

        original_history = await attached_history()
        assert [event for event in original_history["replayEvents"]
                if event["name"] == "karen.verified_attachment_history.v1"] == [{
            "type": "CUSTOM", "name": "karen.verified_attachment_history.v1",
            "messageId": messages[1].id,
            "value": {"user_message_id": messages[0].id, "attachment_count": 1},
        }]
        assert active_ref["source_id"] not in str(original_history)
        assert active_ref["revision"] not in str(original_history)
        assert (await attached_history(text_only=True))["replayEvents"] == []
        async with engine.begin() as conn:
            saved = (await conn.execute(text(
                "SELECT message_metadata FROM public.messages WHERE message_id = CAST(:id AS uuid)"
            ), {"id": messages[1].id})).scalar_one()
            assert saved[COMPLETED_ATTACHMENT_RECEIPT_KEY] == receipt
            await conn.execute(text(
                "UPDATE public.messages SET message_metadata = message_metadata || "
                "'{\"tampered\": true}'::jsonb WHERE message_id = CAST(:id AS uuid)"
            ), {"id": messages[0].id})
        assert not (await readback(completing, ctx, messages)).success
        with pytest.raises(UnreplayableHistory):
            await attached_history()
        async with engine.begin() as conn:
            await conn.execute(text(
                "UPDATE public.messages SET message_metadata = message_metadata - 'tampered' "
                "WHERE message_id = CAST(:id AS uuid)"
            ), {"id": messages[0].id})
        assert (await readback(completing, ctx, messages)).success
        assert await attached_history() == original_history
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
        # Exact reconciliation must return the original committed submission,
        # not the most recent run. Exercise the real ledger under a temporary
        # non-bypass PostgreSQL role, not the fixture's database creator.
        # Role creation and grants are rolled back with the transaction.
        role = "submission_reader_" + uuid4().hex
        async with factory() as session:
            await session.begin()
            try:
                await session.execute(text(
                    f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOBYPASSRLS'
                ))
                await session.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
                await session.execute(text(
                    'GRANT SELECT ON public.runtime_chat_runs, public.conversations, '
                    f'public.messages TO "{role}"'
                ))
                await session.execute(text(f'SET LOCAL ROLE "{role}"'))
                role_evidence = (await session.execute(text(
                    "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                ))).one()
                assert tuple(role_evidence) == (role, False, False)

                @asynccontextmanager
                async def restricted_scope(tenant_id, *, user_id):
                    await session.execute(text(
                        "SELECT set_config('app.current_tenant_id', :tenant, true)"
                    ), {"tenant": tenant_id})
                    await session.execute(text(
                        "SELECT set_config('app.current_user_id', :owner, true)"
                    ), {"owner": user_id})
                    yield session

                async def submission_status(run, *, tid=tenant, uid=owner, cid=conversation):
                    return await runs.read_submission_status(
                        tenant_id=tid, user_id=uid, conversation_id=cid,
                        submission_id=run.submission_id,
                    )

                with monkeypatch.context() as restricted:
                    restricted.setattr(
                        chat_run_repository, "async_transaction_scope", restricted_scope,
                    )
                    assert await submission_status(completing) == {
                        "runId": "complete-private", "submissionId": completing.submission_id,
                        "status": "completed", "cancel_requested": False,
                        "cancellation_confirmed": False,
                    }
                    assert (await submission_status(older))["runId"] == "older-completion"
                    assert (await submission_status(cancelled))["status"] == "cancelled"
                    assert (await submission_status(lease))["status"] == "failed"
                    assert await submission_status(completing, uid=other_owner) is None
                    assert await submission_status(completing, tid=other_tenant) is None
                    assert await submission_status(completing, cid=str(uuid4())) is None
                    assert await runs.read_submission_status(
                        tenant_id=tenant, user_id=owner, conversation_id=conversation,
                        submission_id="unknown-submission",
                    ) is None
                    # Verify that RLS itself denies foreign rows even without
                    # the repository's redundant explicit owner predicates.
                    for tid, uid in ((tenant, other_owner), (other_tenant, owner)):
                        async with restricted_scope(tid, user_id=uid) as scoped:
                            count = (await scoped.execute(text(
                                "SELECT count(*) FROM public.runtime_chat_runs "
                                "WHERE submission_id = :submission"
                            ), {"submission": completing.submission_id})).scalar_one()
                            assert count == 0
            finally:
                await session.rollback()
        assert await observe(completing) == ("completed", 2)
        assert await observe(cancelled) == ("cancelled", 0)
        assert (await repo.get_composer_draft_with_attachments(
            conversation, tenant, user_id=owner,
        )).data == newer.data
        # Exercise actual runtime persistence and canonical history on a separate
        # conversation without attachments. The source/model boundary is a
        # controlled fixture; PostgreSQL writes, run attestation and reads are real.
        citation_thread = str(uuid4())
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO conversations (conversation_id, tenant_id, user_id) "
                "VALUES (CAST(:c AS uuid), CAST(:t AS uuid), CAST(:u AS uuid))"
            ), {"c": citation_thread, "t": tenant, "u": owner})
        gateway = ConversationRuntimeGateway(repo)
        runtime = object.__new__(ChatRuntime)
        runtime._conversation_gateway = gateway
        runtime._emitter = MagicMock()
        runtime._freeze_persona_snapshot = AsyncMock(return_value=SimpleNamespace(
            status="none", persona_id=None, memory_filter_required=False,
        ))
        url = "https://example.org/history"
        answer = "Source: " + url
        sources = [{"url": url, "evidence_level": "fetched_page",
                    "content": "controlled source passage"}]
        verdict = ResponseValidator().validate(answer, ResponseContract(
            purpose="tool_synthesis", requires_live_data=True,
            tool_results=[{"sources": sources}],
        ))
        assert verdict.valid and verdict.verified_citation_urls == (url,)

        async def citation_run(run_id):
            run = await runs.admit(
                tenant_id=tenant, user_id=owner, conversation_id=citation_thread,
                transport_run_id=run_id, request_id=run_id, correlation_id=run_id,
            )
            assert run is not None
            context = ChatExecutionContext(
                tenant_id=tenant, user_id=owner, session_id=citation_thread,
                conversation_id=citation_thread, request_id=run_id, correlation_id=run_id,
            )
            context.authenticated_user = UserData(
                user_id=owner, tenant_id=tenant, roles=["user"], permissions=[],
                is_active=True, is_verified=True,
            )
            request = ChatExecutionRequest(
                context=context, messages=[{"role": "user", "content": "Research history"}],
                runtime_run_lease=run,
            )
            metadata = {
                "actual_provider": "fixture-local", "actual_model": "fixture-model",
                "runtime_engine": "fixture", "response_source": "grounded_search_model",
                "answer_composition_status": "grounded_model", "degraded_mode": False,
                "provider_attempts": [
                    {"type": "tool", "id": "internet_search", "status": "success"},
                ],
                "sources": sources,
                "verified_citation_receipt_v1": {
                    "schema_version": 1, "request_id": run_id,
                    "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
                    "source_kind": "tool", "source_id": "internet_search",
                    "urls": verdict.verified_citation_urls,
                },
            }
            return run, request, metadata

        async def citation_attestations(*, tid=tenant, uid=owner):
            return await runs.completed_replay_attestations(
                tenant_id=tid, user_id=uid, conversation_id=citation_thread,
            )

        citation, request, metadata = await citation_run("citation-completion")
        # Fail the assistant INSERT after the user INSERT. The nontransactional
        # witness distinguishes a reached fault from unrelated setup failure.
        async with engine.begin() as conn:
            await conn.execute(text("CREATE SEQUENCE citation_fault_witness"))
            await conn.execute(text("""
                CREATE FUNCTION reject_citation_write() RETURNS trigger
                LANGUAGE plpgsql AS $citation$
                BEGIN
                    PERFORM nextval('citation_fault_witness');
                    RAISE EXCEPTION 'controlled citation write failure' USING ERRCODE = '23514';
                END;
                $citation$
            """))
            await conn.execute(text("""
                CREATE TRIGGER reject_citation BEFORE INSERT ON public.messages
                FOR EACH ROW WHEN (NEW.role = 'assistant'
                    AND NEW.message_metadata ? 'verified_citation_receipt_v1')
                EXECUTE FUNCTION reject_citation_write()
            """))
        failed = await runtime._persist_transcript(request, answer, metadata)
        assert not failed.success
        assert await observe(citation) == ("running", 0)
        assert await citation_attestations() == {}
        async with engine.begin() as conn:
            witness = (await conn.execute(text(
                "SELECT last_value, is_called FROM citation_fault_witness"
            ))).one()
            assert tuple(witness) == (1, True)
            await conn.execute(text("DROP TRIGGER reject_citation ON public.messages"))

        persisted = await runtime._persist_transcript(request, answer, metadata)
        assert persisted.success and persisted.persisted_messages == 2
        assert await observe(citation) == ("completed", 2)
        snapshot = await gateway.get_owned_snapshot(request.context, message_limit=501)
        assert len(snapshot.messages) == 2
        assistant = snapshot.messages[-1]
        assert assistant.role == "assistant"
        assert assistant.metadata["verified_citation_receipt_v1"] == {
            **metadata["verified_citation_receipt_v1"], "urls": [url],
        }
        proofs = await citation_attestations()
        assert proofs == {assistant.id: (citation.request_id, canonical_message_digest(assistant))}
        history = project_owned_history(snapshot, attestations=proofs)
        assert [event for event in history["replayEvents"]
                if event["name"] == "karen.verified_citations.v1"] == [{
            "type": "CUSTOM", "name": "karen.verified_citations.v1",
            "messageId": assistant.id, "value": {"urls": [url]},
        }]
        assert "controlled source passage" not in str(history)
        assert project_owned_history(snapshot, attestations=proofs,
                                     text_continuation=True)["replayEvents"] == []

        # Change actual stored JSONB without updating the completed-run digest.
        async with engine.begin() as conn:
            await conn.execute(text("""
                UPDATE public.messages
                SET message_metadata = jsonb_set(message_metadata,
                    '{verified_citation_receipt_v1,source_id}', '"other-tool"'::jsonb)
                WHERE message_id = CAST(:id AS uuid)
            """), {"id": assistant.id})
        tampered = await gateway.get_owned_snapshot(request.context, message_limit=501)
        with pytest.raises(UnreplayableHistory):
            project_owned_history(tampered, attestations=await citation_attestations())
        async with engine.begin() as conn:
            await conn.execute(text("""
                UPDATE public.messages
                SET message_metadata = jsonb_set(message_metadata,
                    '{verified_citation_receipt_v1,source_id}', '"internet_search"'::jsonb)
                WHERE message_id = CAST(:id AS uuid)
            """), {"id": assistant.id})
        restored = await gateway.get_owned_snapshot(request.context, message_limit=501)
        assert project_owned_history(restored, attestations=await citation_attestations()) == history

        stopped, stopped_request, stopped_meta = await citation_run("citation-cancelled")
        assert await runs.finish(stopped, status="cancelled")
        assert not (await runtime._persist_transcript(stopped_request, answer, stopped_meta)).success
        assert await observe(stopped) == ("cancelled", 0)
        assert await citation_attestations() == proofs

        # Reuse the existing restricted-role pattern: no creator-role bypass
        # can make foreign ledger attestations appear legitimate.
        role = "citation_reader_" + uuid4().hex
        async with factory() as session:
            await session.begin()
            try:
                await session.execute(text(
                    f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOBYPASSRLS'
                ))
                await session.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
                await session.execute(text(
                    'GRANT SELECT ON public.runtime_chat_runs, public.conversations, '
                    f'public.messages TO "{role}"'
                ))
                await session.execute(text(f'SET LOCAL ROLE "{role}"'))
                assert tuple((await session.execute(text(
                    "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                ))).one()) == (role, False, False)

                @asynccontextmanager
                async def citation_scope(tenant_id, *, user_id):
                    await session.execute(text(
                        "SELECT set_config('app.current_tenant_id', :tenant, true)"
                    ), {"tenant": tenant_id})
                    await session.execute(text(
                        "SELECT set_config('app.current_user_id', :owner, true)"
                    ), {"owner": user_id})
                    yield session

                with monkeypatch.context() as restricted:
                    restricted.setattr(chat_run_repository, "async_transaction_scope", citation_scope)
                    assert await citation_attestations() == proofs
                    assert await citation_attestations(uid=other_owner) == {}
                    assert await citation_attestations(tid=other_tenant) == {}
                    for tid, uid in ((tenant, other_owner), (other_tenant, owner)):
                        async with citation_scope(tid, user_id=uid) as scoped:
                            count = (await scoped.execute(text(
                                "SELECT count(*) FROM public.runtime_chat_runs "
                                "WHERE request_id = :request"
                            ), {"request": citation.request_id})).scalar_one()
                            assert count == 0
            finally:
                await session.rollback()

        # Explicit retry only advances the original retained revision. The
        # completed/cancelled ledger rows and transcript are never rewritten.
        async def retry(lease, content, refs, *, principal=owner, tid=tenant):
            return await runs.advance_failed_draft_revision(
                tenant_id=tid, user_id=principal, conversation_id=conversation,
                submission_id=lease.submission_id, submitted_text=content,
                attachment_references=refs,
            )

        async def retry_observation(lease, *, principal=owner, tid=tenant):
            return await runs.read_failed_draft_revision(
                tenant_id=tid, user_id=principal, conversation_id=conversation,
                submission_id=lease.submission_id,
            )

        async def retry_eligibility(lease, *, principal=owner, tid=tenant):
            observed = await retry_observation(lease, principal=principal, tid=tid)
            if observed["eligible"]:
                return int(lease.submission_id.split("-")[2])
            return None

        assert await retry_eligibility(completing) is None
        assert await retry_eligibility(cancelled, principal=other_owner) is None
        assert await retry_eligibility(cancelled, tid=other_tenant) is None
        assert await retry_eligibility(cancelled) == 7
        assert await retry(completing, attached.data["text"], [active_ref]) is None
        assert await retry(cancelled, newer.data["text"], [active_ref], principal=other_owner) is None
        assert await retry(cancelled, newer.data["text"], [active_ref], tid=other_tenant) is None
        assert await retry(cancelled, "different text", [active_ref]) is None
        # A failure after the SQL UPDATE but before commit must roll back
        # the revision, preserving eligibility. Observe the write inside
        # the actual transaction before injecting the failure.
        @asynccontextmanager
        async def rollback_retry_scope(tenant_id, *, user_id):
            async with real_scope(tenant_id, user_id=user_id) as session:
                yield session
                revision = (await session.execute(text("""
                    SELECT revision FROM public.conversation_composer_drafts
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND user_id = CAST(:owner AS uuid)
                      AND conversation_id = CAST(:conversation AS uuid)
                """), {"tenant": tenant, "owner": owner,
                       "conversation": conversation})).scalar_one()
                assert revision == 8
                marker = (await session.execute(text("""
                    SELECT retry_prepared_revision FROM public.runtime_chat_runs
                    WHERE execution_id = CAST(:execution AS uuid)
                """), {"execution": cancelled.execution_id})).scalar_one()
                assert marker == 8
                raise RuntimeError("controlled retry rollback")

        with monkeypatch.context() as fault:
            fault.setattr(chat_run_repository, "async_transaction_scope", rollback_retry_scope)
            with pytest.raises(RuntimeError, match="controlled retry rollback"):
                await retry(cancelled, newer.data["text"], [active_ref])
        assert await retry_eligibility(cancelled) == 7
        assert (await retry_observation(cancelled))["prepared_revision"] is None
        assert await observe(cancelled) == ("cancelled", 0)
        assert (await repo.get_composer_draft_with_attachments(
            conversation, tenant, user_id=owner,
        )).data == newer.data

        # Two explicit retry requests for the same original identity may
        # produce at most one revision advance.
        retried = await asyncio.gather(
            retry(cancelled, newer.data["text"], [active_ref]),
            retry(cancelled, newer.data["text"], [active_ref]),
        )
        assert retried.count(8) == 1 and retried.count(None) == 1
        assert await retry_observation(cancelled) == {
            "eligible": False, "prepared_revision": 8, "prepared_current": True,
        }
        for principal, tid in [(other_owner, tenant), (owner, other_tenant)]:
            assert await retry_observation(cancelled, principal=principal, tid=tid) == {
                "eligible": False, "prepared_revision": None, "prepared_current": False,
            }
        assert await retry_eligibility(cancelled) is None
        assert await retry(cancelled, newer.data["text"], [active_ref]) is None
        assert await observe(cancelled) == ("cancelled", 0)
        assert (await repo.get_composer_draft_with_attachments(
            conversation, tenant, user_id=owner,
        )).data == {**newer.data, "revision": 8}
        failed_retry = await admit("retry-fails", 8, [active_ref], newer.data["text"])
        assert failed_retry is not None
        assert await retry_observation(cancelled) == {
            "eligible": False, "prepared_revision": 8, "prepared_current": False,
        }
        assert await retry(failed_retry, newer.data["text"], [active_ref]) is None
        assert await retry_eligibility(failed_retry) is None
        assert await runs.finish(failed_retry, status="failed", error_code="CHAT_TEST_TERMINAL")
        # The successor's failed terminal state retains the same draft and
        # removes the unresolved fence, but it has already been admitted.
        # Only the successor can now authorize another retry preparation.
        assert await retry_observation(cancelled) == {
            "eligible": False, "prepared_revision": 8, "prepared_current": False,
        }
        assert await retry_eligibility(failed_retry) == 8
        # A successful database commit followed by a lost response must
        # not allow the old submission to advance a second time.
        @asynccontextmanager
        async def lost_retry_receipt_scope(tenant_id, *, user_id):
            async with real_scope(tenant_id, user_id=user_id) as session:
                yield session
            raise RuntimeError("controlled lost retry receipt")

        with monkeypatch.context() as fault:
            fault.setattr(chat_run_repository, "async_transaction_scope", lost_retry_receipt_scope)
            with pytest.raises(RuntimeError, match="controlled lost retry receipt"):
                await retry(failed_retry, newer.data["text"], [active_ref])
        assert await retry_eligibility(failed_retry) is None
        assert await retry_observation(failed_retry) == {
            "eligible": False, "prepared_revision": 9, "prepared_current": True,
        }
        assert await retry(failed_retry, newer.data["text"], [active_ref]) is None
        assert (await repo.get_composer_draft_with_attachments(
            conversation, tenant, user_id=owner,
        )).data == {**newer.data, "revision": 9}
        assert await observe(failed_retry) == ("failed", 0)
        assert await admit("retry-original-replay", 8, [active_ref], newer.data["text"]) is None
        # A newer explicit edit is never overwritten by retry recovery.
        latest = await write(9, [active_ref], "Newer retry draft")
        assert latest.success and latest.data["revision"] == 10
        assert await retry_observation(failed_retry) == {
            "eligible": False, "prepared_revision": 9, "prepared_current": False,
        }
        assert await retry(failed_retry, newer.data["text"], [active_ref]) is None
        assert (await repo.get_composer_draft_with_attachments(
            conversation, tenant, user_id=owner,
        )).data == latest.data
        # Expired leases and orphaned rows remain unresolved, not retryable.
        expired = await admit("retry-expired", 10, [active_ref], latest.data["text"])
        assert expired is not None
        async with real_scope(tenant, user_id=owner) as session:
            await session.execute(text("""
                UPDATE public.runtime_chat_runs
                SET lease_expires_at = NOW() - INTERVAL '1 second'
                WHERE execution_id = CAST(:execution AS uuid)
            """), {"execution": expired.execution_id})
        assert await retry_eligibility(expired) is None
        assert await retry(expired, latest.data["text"], [active_ref]) is None
        assert await admit("retry-orphan-reconcile", 10, [active_ref], latest.data["text"]) is None
        assert await observe(expired) == ("orphaned", 0)
        assert await retry_eligibility(expired) is None
        assert await retry(expired, latest.data["text"], [active_ref]) is None
        assert (await repo.get_composer_draft_with_attachments(
            conversation, tenant, user_id=owner,
        )).data == latest.data
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
