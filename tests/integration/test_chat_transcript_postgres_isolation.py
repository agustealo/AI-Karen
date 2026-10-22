from __future__ import annotations

import asyncio
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
        response_metadata={
            "actual_provider": "ollama",
            "actual_model": "local-model",
            "response_source": "grounded_observation_model",
            "structured_content": {"presentation": {"type": "weather", "temperature": 20}},
        },
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

    # Read through a fresh gateway instance using durable PostgreSQL state.
    restored = await ConversationRuntimeGateway(
        repository=PostgresConversationRepository(session_factory=session_factory)
    ).load_history(
        _context(
            tenant_id=tenant_a, user_id=user_a, session_id="shared-session",
            request_id=str(uuid.uuid4()), conversation_id=attacked_conversation_id,
        ),
        limit=20,
    )
    assert restored.status == "loaded"
    saved_assistant = next(row for row in restored.messages if row.role == "assistant")
    assert saved_assistant.metadata["actual_provider"] == "ollama"
    assert saved_assistant.metadata["actual_model"] == "local-model"
    assert saved_assistant.metadata["response_source"] == "grounded_observation_model"
    assert saved_assistant.metadata["structured_content"]["presentation"]["temperature"] == 20

    conflict = await owner_gateway.persist_completed_turn(
        owner_context,
        user_text="Tenant A durable context.",
        assistant_text="Conflicting assistant response.",
    )
    assert conflict.status == "failed"
    after_conflict = await repository.get_messages(attacked_conversation_id, tenant_a, limit=20)
    assert after_conflict.success
    assert len(after_conflict.data or []) == 2
    assert next(row for row in after_conflict.data if row.role == "assistant").content == (
        "Tenant A durable response."
    )

    # Force an assistant insert to fail inside the pair transaction.
    # The user half must not survive that failure.
    async with engine.begin() as connection:
        await connection.execute(text("""
            CREATE FUNCTION reject_atomic_assistant() RETURNS trigger AS '
            BEGIN
                IF NEW.role = ''assistant'' AND NEW.content = ''INJECTED_FAILURE'' THEN
                    RAISE EXCEPTION ''injected_assistant_failure'';
                END IF;
                RETURN NEW;
            END;
            ' LANGUAGE plpgsql
        """))
        await connection.execute(text("""
            CREATE TRIGGER reject_atomic_assistant_trigger
            BEFORE INSERT ON messages
            FOR EACH ROW EXECUTE FUNCTION reject_atomic_assistant()
        """))

    rollback_context = _context(
        tenant_id=tenant_a, user_id=user_a,
        session_id="rollback-session", request_id=str(uuid.uuid4()),
    )
    rollback_result = await owner_gateway.persist_completed_turn(
        rollback_context, user_text="atomic rollback input",
        assistant_text="INJECTED_FAILURE",
    )
    assert rollback_result.status == "failed"
    rollback_rows = await repository.get_messages(
        rollback_result.conversation_id, tenant_a, limit=20,
    )
    assert rollback_rows.success
    assert rollback_rows.data == []

    # Repeated identical calls must resolve under the same conversation row
    # lock without creating duplicate user/assistant pairs.
    concurrent_context = _context(
        tenant_id=tenant_a, user_id=user_a,
        session_id="concurrent-session", request_id=str(uuid.uuid4()),
    )
    concurrent = await asyncio.gather(*[
        owner_gateway.persist_completed_turn(
            concurrent_context, user_text="concurrent question",
            assistant_text="concurrent answer",
        )
        for _ in range(4)
    ])
    assert sorted(result.status for result in concurrent) == [
        "already_persisted", "already_persisted",
        "already_persisted", "persisted",
    ]
    concurrent_rows = await repository.get_messages(
        concurrent[0].conversation_id, tenant_a, limit=20,
    )
    assert concurrent_rows.success
    assert len(concurrent_rows.data or []) == 2

    async with engine.begin() as connection:
        await connection.execute(text("DROP TRIGGER reject_atomic_assistant_trigger ON messages"))
        await connection.execute(text("DROP FUNCTION reject_atomic_assistant()"))

    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS messages CASCADE"))
        await connection.execute(text("DROP TABLE IF EXISTS conversations CASCADE"))
    await engine.dispose()
