"""Real PostgreSQL draft CAS and artifact ownership proof on disposable CI DB."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.services.database.repositories.postgres_conversation_repository import (
    PostgresConversationRepository,
)


@pytest.mark.asyncio
async def test_attachment_draft_atomic_cas_and_owner_scope():
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
                    user_id uuid NOT NULL
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
                "INSERT INTO conversations VALUES (CAST(:c AS uuid), CAST(:t AS uuid), CAST(:u AS uuid))"
            ), {"c": conversation, "t": tenant, "u": owner})
            for sid, tid, uid in (
                (source, tenant, owner), (foreign, tenant, other_owner),
                (archived, tenant, owner), (cross_tenant, other_tenant, owner),
            ):
                await conn.execute(text(
                    "INSERT INTO files VALUES (:s, :t, CAST(:u AS uuid), :d, NULL)"
                ), {"s": sid, "t": tid, "u": uid, "d": digest})
            await conn.execute(text("UPDATE files SET deleted_at = NOW() WHERE file_id = :s"), {"s": archived})
        repo = PostgresConversationRepository(async_sessionmaker(engine, expire_on_commit=False))

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
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE files SET deleted_at = NOW() WHERE file_id = :s"), {"s": source})
        assert not (await write(2, [ref])).success
        cleared = await write(2, [], "cleared")
        assert cleared.success and cleared.data["revision"] == 3
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
                    (3, "different text", False),
                    (3, "cleared", True),
                ):
                    assert await repo.lock_matching_submission_draft(
                        session, tenant_id=tenant, user_id=owner,
                        conversation_id=conversation, revision=revision,
                        submitted_text=submitted_text,
                    ) is expected
    finally:
        if engine is not None:
            await engine.dispose()
        try:
            if created:
                async with admin.connect() as conn:
                    await conn.execute(text(f'DROP DATABASE "{db_name}"'))
        finally:
            await admin.dispose()
