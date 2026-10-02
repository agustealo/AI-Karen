from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    ConversationRuntimeGateway,
)
from ai_karen_engine.services.database.repositories.conversation_repository import Message
from ai_karen_engine.services.database.repositories.postgres_conversation_repository import (
    PostgresConversationRepository,
)


pytestmark = pytest.mark.asyncio


def _context(
    *,
    tenant_id: str,
    user_id: str,
    session_id: str,
    request_id: str,
    conversation_id: str | None = None,
) -> ChatExecutionContext:
    return ChatExecutionContext(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        conversation_id=conversation_id,
        request_id=request_id,
        correlation_id=f"correlation-{request_id}",
    )


async def test_real_postgres_rejects_cross_tenant_transcript_read_append_and_replay() -> None:
    """Burn the canonical repository against real PostgreSQL tenant boundaries."""

    database_url = os.environ["CHAT_TEST_DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS messages CASCADE"))
        await connection.execute(text("DROP TABLE IF EXISTS conversations CASCADE"))
        await connection.execute(
            text(
                """
                CREATE TABLE conversations (
                    conversation_id UUID PRIMARY KEY,
                    user_id UUID NOT NULL,
                    title TEXT,
                    conversation_metadata JSONB DEFAULT '{}'::jsonb,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT now(),
                    updated_at TIMESTAMP DEFAULT now(),
                    session_id TEXT,
                    ui_context JSONB DEFAULT '{}'::jsonb,
                    ai_insights JSONB DEFAULT '{}'::jsonb,
                    user_settings JSONB DEFAULT '{}'::jsonb,
                    summary TEXT,
                    tags TEXT[],
                    last_ai_response_id TEXT,
                    tenant_id UUID NOT NULL
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                CREATE TABLE messages (
                    message_id UUID PRIMARY KEY,
                    conversation_id UUID NOT NULL
                        REFERENCES conversations(conversation_id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    message_metadata JSONB DEFAULT '{}'::jsonb,
                    function_call JSONB,
                    function_response JSONB,
                    created_at TIMESTAMP DEFAULT now()
                )
                """
            )
        )

    repository = PostgresConversationRepository(session_factory=session_factory)
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())

    owner_context = _context(
        tenant_id=tenant_a,
        user_id=user_a,
        session_id="shared-session",
        request_id=str(uuid.uuid4()),
    )
    owner_gateway = ConversationRuntimeGateway(repository=repository)
    persisted = await owner_gateway.persist_completed_turn(
        owner_context,
        user_text="Tenant A durable context.",
        assistant_text="Tenant A durable response.",
    )

    assert persisted.status == "persisted"
    assert persisted.persisted_messages == 2
    attacked_conversation_id = persisted.conversation_id

    attacker_context = _context(
        tenant_id=tenant_b,
        user_id=user_b,
        session_id="shared-session",
        request_id=str(uuid.uuid4()),
        conversation_id=attacked_conversation_id,
    )
    attacker_gateway = ConversationRuntimeGateway(repository=repository)

    history = await attacker_gateway.load_history(attacker_context, limit=20)
    assert history.status == "not_found"
    assert history.messages == ()

    with pytest.raises(RuntimeError, match="conversation_not_found"):
        await attacker_gateway.append_message(
            attacker_context,
            role="user",
            content="Cross-tenant append must fail.",
        )

    replay = await repository.add_message(
        Message(
            id=persisted.user_message_id or str(uuid.uuid4()),
            conversation_id=attacked_conversation_id,
            tenant_id=tenant_b,
            role="user",
            content="Tenant A durable context.",
            metadata={"request_id": attacker_context.request_id},
        )
    )
    assert replay.success is False
    assert replay.error == "conversation_not_found_or_tenant_mismatch"

    tenant_b_rows = await repository.get_messages(
        attacked_conversation_id,
        tenant_b,
        limit=20,
    )
    assert tenant_b_rows.success is True
    assert tenant_b_rows.data == []

    tenant_a_rows = await repository.get_messages(
        attacked_conversation_id,
        tenant_a,
        limit=20,
    )
    assert tenant_a_rows.success is True
    assert [message.content for message in tenant_a_rows.data or []] == [
        "Tenant A durable context.",
        "Tenant A durable response.",
    ]

    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS messages CASCADE"))
        await connection.execute(text("DROP TABLE IF EXISTS conversations CASCADE"))
    await engine.dispose()
