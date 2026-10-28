"""Isolated subprocess probe for CK-07F5's disposable PostgreSQL test.

This is a test-only harness: it calls the canonical SqlChatRunRepository,
never hosts a model, chooses a provider, writes schema, or reads a real user's
conversation. The parent requires a dedicated database named karen_chat_run_test.
Do not run this module as an application worker.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.persistence.repositories import chat_run_repository
from ai_karen_engine.persistence.repositories.chat_run_repository import (
    SqlChatRunRepository,
)


async def probe() -> None:
    if os.getenv("KAREN_CI_RUN_CHILD_PROBE") != "1":
        raise RuntimeError("Explicit disposable database probe approval required")
    raw_url = os.getenv("CHAT_RUN_TEST_DATABASE_URL", "")
    normalized = raw_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    if (
        parsed.scheme != "postgresql"
        or parsed.path != "/karen_chat_run_test"
        or not parsed.hostname
    ):
        raise RuntimeError("Refusing a non-disposable PostgreSQL endpoint")

    tenant = str(UUID(os.environ["KAREN_CI_RUN_CHILD_TENANT_ID"]))
    user = str(UUID(os.environ["KAREN_CI_RUN_CHILD_USER_ID"]))
    conversation = str(UUID(os.environ["KAREN_CI_RUN_CHILD_CONVERSATION_ID"]))
    run_id = os.environ["KAREN_CI_RUN_CHILD_TRANSPORT_ID"]
    if run_id != "run-external-process":
        raise RuntimeError("Unexpected probe run identity")

    engine = create_async_engine(
        "postgresql+asyncpg://" + normalized.split("://", 1)[1],
        pool_size=1,
        max_overflow=0,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def scoped_transaction(tenant_id: str, *, user_id: str):
        async with sessions() as session:
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

    try:
        # Scope the inherited production owner through its existing transaction
        # API. This is deliberately a different Python interpreter and engine.
        chat_run_repository.async_transaction_scope = scoped_transaction
        runtime = SqlChatRunRepository()
        scope = {
            "tenant_id": tenant,
            "user_id": user,
            "conversation_id": conversation,
            "transport_run_id": run_id,
        }
        assert await runtime.read_status(**scope) == {
            "status": "running",
            "cancel_requested": False,
            "cancellation_confirmed": False,
        }
        assert await runtime.request_cancel(**scope) == "cancelling"
        assert await runtime.read_status(**scope) == {
            "status": "cancelling",
            "cancel_requested": True,
            "cancellation_confirmed": False,
        }
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(probe())
