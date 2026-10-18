"""Real PostgreSQL channel claim/race proof on a disposable dedicated database.

Runs only with CHANNEL_TEST_DATABASE_URL pointing to a database whose name is
exactly karen_channel_test. This test is destructive to that dedicated database.
It executes the checked-in channel migration and the actual repository SQL.
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

from ai_karen_engine.persistence.repositories import channel_repository as module
from ai_karen_engine.persistence.repositories.channel_repository import SqlChannelRepository


@pytest.mark.asyncio
async def test_live_postgres_outbound_race_and_unknown_quarantine(monkeypatch):
    url = os.getenv("CHANNEL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Dedicated CHANNEL_TEST_DATABASE_URL is not configured")
    if urlparse(url).path != "/karen_channel_test":
        pytest.fail("Live channel test must use the dedicated karen_channel_test database")

    dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    raw = await asyncpg.connect(dsn)
    tenant_a, tenant_b, user, binding, inbox, delivery = [
        uuid.uuid4() for _ in range(6)
    ]
    connection_id = f"live-channel-{uuid.uuid4().hex}"
    engine = None
    try:
        # Disposable dedicated DB, with only prerequisites of the migration.
        await raw.execute("""
            DROP TABLE IF EXISTS public.channel_outbox CASCADE;
            DROP TABLE IF EXISTS public.channel_inbox CASCADE;
            DROP TABLE IF EXISTS public.channel_link_challenges CASCADE;
            DROP TABLE IF EXISTS public.channel_identity_bindings CASCADE;
            DROP TABLE IF EXISTS public.channel_connections CASCADE;
            DROP TABLE IF EXISTS public.auth_users CASCADE;
            DROP TABLE IF EXISTS public.tenants CASCADE;
            CREATE TABLE public.tenants (id uuid PRIMARY KEY);
            CREATE TABLE public.auth_users (
                user_id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
                is_active boolean NOT NULL, is_verified boolean NOT NULL
            );
        """)
        migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261017010000_31_channel_gateway_durable_admission.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(migration)
        await raw.execute(
            "INSERT INTO public.tenants(id) VALUES($1),($2)", tenant_a, tenant_b,
        )
        await raw.execute(
            """INSERT INTO public.auth_users
               (user_id,tenant_id,is_active,is_verified)
               VALUES ($1,$2,true,true)""", user, tenant_a,
        )
        await raw.execute(
            """INSERT INTO public.channel_connections
               (connection_id,tenant_id,installation_id,provider_account_id,
                credential_handle,enabled,revision)
               VALUES ($1,$2,'telegram-bot','demo','vault://test',true,1)""",
            connection_id, tenant_a,
        )
        await raw.execute(
            """INSERT INTO public.channel_identity_bindings
               (binding_id,tenant_id,connection_id,external_sender_id,user_id,
                verified_at)
               VALUES ($1,$2,$3,'sender',$4,now())""",
            binding, tenant_a, connection_id, user,
        )
        await raw.execute(
            """INSERT INTO public.channel_inbox
               (inbox_id,tenant_id,connection_id,connection_revision,
                external_event_id,external_sender_id,external_conversation_id,
                message_kind,message_text,event_digest,status,binding_id,user_id)
               VALUES ($1,$2,$3,1,'event','sender','room','text','hello',$4,
                       'completed',$5,$6)""",
            inbox, tenant_a, connection_id, "a" * 64, binding, user,
        )
        await raw.execute(
            """INSERT INTO public.channel_outbox
               (delivery_id,tenant_id,connection_id,inbox_id,destination_id,
                idempotency_key,message_kind,message_text)
               VALUES ($1,$2,$3,$4,'room','event','text','answer')""",
            delivery, tenant_a, connection_id, inbox,
        )

        engine = create_async_engine(
            "postgresql+asyncpg://" + dsn.split("://", 1)[1],
            pool_size=4, max_overflow=0,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)

        @asynccontextmanager
        async def real_scope(tenant_id: str):
            async with factory() as session:
                async with session.begin():
                    await session.execute(
                        text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                        {"tenant": tenant_id},
                    )
                    yield session

        monkeypatch.setattr(module, "async_transaction_scope", real_scope)
        first, second = await asyncio.gather(
            SqlChannelRepository().claim_outbound(
                tenant_id=str(tenant_a), delivery_id=str(delivery), lease_seconds=90,
            ),
            SqlChannelRepository().claim_outbound(
                tenant_id=str(tenant_a), delivery_id=str(delivery), lease_seconds=90,
            ),
        )
        assert sum(value is not None for value in (first, second)) == 1
        winner = first or second
        assert winner is not None and winner.user_id == str(user)
        assert await SqlChannelRepository().claim_outbound(
            tenant_id=str(tenant_b), delivery_id=str(delivery), lease_seconds=90,
        ) is None

        await raw.execute(
            """UPDATE public.channel_outbox SET claim_expires_at =
               clock_timestamp() - interval '10 seconds'
               WHERE delivery_id = $1""", delivery,
        )
        quarantined = await SqlChannelRepository().quarantine_expired_outbound_claims(
            tenant_id=str(tenant_a),
        )
        assert quarantined == [str(delivery)]
        state = await raw.fetchrow(
            """SELECT status,attempt_count,claim_token,claim_expires_at
               FROM public.channel_outbox WHERE delivery_id=$1""", delivery,
        )
        assert state["status"] == "unknown"
        assert state["attempt_count"] == 1
        assert state["claim_token"] is None
        assert state["claim_expires_at"] is None
        assert await SqlChannelRepository().claim_outbound(
            tenant_id=str(tenant_a), delivery_id=str(delivery), lease_seconds=90,
        ) is None
        assert await SqlChannelRepository().list_unattempted_outbound(
            tenant_id=str(tenant_a), connection_id=connection_id,
        ) == []
    finally:
        if engine is not None:
            await engine.dispose()
        await raw.close()
