"""Opt-in real PostgreSQL proof for durable approved presentation metadata.

Requires an explicitly disposable, migrated database and an already seeded
tenant-owned conversation. Never creates schema or changes production records.
"""
from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.core.runtime.presentation_contract import validate_presentation

pytestmark = pytest.mark.asyncio

@pytest.mark.skipif(
    os.getenv("KAREN_TEST_DISPOSABLE_DATABASE") != "1"
    or os.getenv("KAREN_TEST_GENERATIVE_SURFACE_POSTGRES") != "1",
    reason="Requires explicitly disposable migrated PostgreSQL fixture",
)
async def test_composed_surface_commits_reopens_and_is_tenant_scoped():
    database_url = os.environ.get("DATABASE_URL", "")
    tenant = os.environ.get("KAREN_TEST_CONVERSATION_TENANT_ID")
    conversation = os.environ.get("KAREN_TEST_CONVERSATION_ID")
    if not tenant or not conversation:
        pytest.skip("No authorized seeded conversation fixture provided")
    if not database_url.startswith(("postgresql+asyncpg://", "postgresql://")):
        pytest.fail("Live surface test requires PostgreSQL")
    url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    message_id = uuid4()
    child = {
        "schema_version": 1, "presentation_id": "clock-proof",
        "component_type": "time.observation", "evidence_ref": "proof:clock",
        "data": {"formatted": "10:15 AM", "timezone": "America/Detroit"},
    }
    composite = validate_presentation({
        "schema_version": 1, "presentation_id": "composite-proof",
        "component_type": "surface.composition", "evidence_ref": "proof:clock",
        "data": {"layout": "stack", "items": [child]},
    })
    assert composite is not None
    metadata = {
        "actual_provider": "test-provider", "actual_model": "test-model",
        "response_source": "grounded_observation_model",
        "presentation_layout_provenance": {"provider": "local-layout", "model": "layout-v1", "response_source": "surface_layout_model", "part_ids": ["clock-proof"]},
        "structured_content": {"presentation": composite},
    }
    import json
    try:
        async with sessions() as session:
            parent = await session.execute(text(
                "SELECT conversation_id FROM conversations "
                "WHERE conversation_id = CAST(:conversation AS uuid) AND tenant_id = CAST(:tenant AS uuid)"
            ), {"conversation": str(UUID(conversation)), "tenant": tenant})
            assert parent.scalar_one_or_none() is not None, "Fixture must be tenant-owned"
            await session.execute(text(
                "INSERT INTO messages (message_id, conversation_id, role, content, message_metadata) "
                "VALUES (CAST(:id AS uuid), CAST(:conversation AS uuid), 'assistant', 'verified surface', CAST(:metadata AS jsonb))"
            ), {"id": str(message_id), "conversation": conversation, "metadata": json.dumps(metadata)})
            await session.commit()
        # New session proves persistence across transaction/session boundaries.
        async with sessions() as session:
            rows = await session.execute(text(
                "SELECT m.message_metadata FROM messages m "
                "JOIN conversations c ON m.conversation_id=c.conversation_id "
                "WHERE m.message_id=CAST(:id AS uuid) AND c.tenant_id=CAST(:tenant AS uuid)"
            ), {"id": str(message_id), "tenant": tenant})
            restored = rows.scalar_one()
            if isinstance(restored, str):
                restored = json.loads(restored)
            assert restored == metadata
            assert restored["presentation_layout_provenance"]["model"] == "layout-v1"
            assert validate_presentation(restored["structured_content"]["presentation"]) == composite
            rows = await session.execute(text(
                "SELECT m.message_id FROM messages m "
                "JOIN conversations c ON m.conversation_id=c.conversation_id "
                "WHERE m.message_id=:id AND c.tenant_id=:tenant"
            ), {"id": str(message_id), "tenant": str(uuid4())})
            assert rows.scalar_one_or_none() is None
    finally:
        async with sessions() as session:
            await session.execute(text(
                "DELETE FROM messages WHERE message_id=CAST(:id AS uuid) AND conversation_id=CAST(:conversation AS uuid)"
            ), {"id": str(message_id), "conversation": conversation})
            await session.commit()
        await engine.dispose()
