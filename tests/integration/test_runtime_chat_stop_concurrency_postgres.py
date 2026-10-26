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
            DROP TABLE IF EXISTS public.auth_users CASCADE;
            DROP TABLE IF EXISTS public.tenants CASCADE;
            CREATE TABLE public.tenants (id uuid PRIMARY KEY);
            CREATE TABLE public.auth_users (
                user_id uuid PRIMARY KEY,
                tenant_id uuid NOT NULL REFERENCES public.tenants(id)
            );
            """
        )
        migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261025020000_43_runtime_chat_run_ledger.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(migration)
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
        assert await worker_b.request_cancel(**identity()) == "cancelling"
        assert not await worker_a.renew(lease)
        assert await worker_a.cancel_requested(lease)
        assert not await worker_a.finish(lease, status="completed")
        assert await worker_a.finish(
            lease, status="cancelled", error_code="CHAT_STREAM_CANCELLED",
        )
        assert await worker_b.request_cancel(**identity()) == "cancelled"
        assert not await worker_b.finish(lease, status="cancelled")

        # Simultaneous stop/completion on two independent connections:
        # serialized SQL transitions must produce exactly one final state.
        race_lease = await worker_a.admit(
            **identity(run_id="run-race"),
            request_id="race-a", correlation_id="race-trace",
        )
        assert race_lease is not None
        stop_result, complete_result = await asyncio.gather(
            worker_b.request_cancel(**identity(run_id="run-race")),
            worker_a.finish(race_lease, status="completed"),
        )
        if complete_result:
            assert stop_result == "completed"
        else:
            assert stop_result == "cancelling"
            assert await worker_a.cancel_requested(race_lease)
            assert await worker_a.finish(
                race_lease, status="cancelled",
                error_code="CHAT_STREAM_CANCELLED",
            )
        observed = await raw.fetchval(
            """
            SELECT status FROM public.runtime_chat_runs
            WHERE execution_id=$1
            """,
            uuid.UUID(race_lease.execution_id),
        )
        assert observed in {"completed", "cancelled"}

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
        assert await worker_b.request_cancel(
            **identity(run_id="run-expired")
        ) == "orphaned"
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
