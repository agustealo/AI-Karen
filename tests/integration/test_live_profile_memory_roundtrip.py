"""Opt-in live PostgreSQL memory read-after-write proof.

Run against an isolated, migrated PostgreSQL test database:
    KAREN_TEST_POSTGRES_MEMORY=1 pytest tests/integration/test_live_profile_memory_roundtrip.py -q

Never enable this against production. No fake stores or monkeypatched sessions.
"""

import os
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from ai_karen_engine.core.memory.signals import MemorySignal
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.derived_projector import PostgresDerivedMemoryProjector
from ai_karen_engine.platform.memory.postgres.ledger_models import MemoryEvent, ProfileFact
from ai_karen_engine.platform.memory.postgres.profile_retriever import PostgresProfileRecallRetriever


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1",
        reason="Requires an explicitly enabled, isolated migrated PostgreSQL test database",
    ),
]


async def test_live_profile_name_roundtrip_scope_and_consent():
    tenant_id, other_tenant = uuid.uuid4(), uuid.uuid4()
    user_id, other_user = uuid.uuid4(), uuid.uuid4()
    event_id = uuid.uuid4()
    value = "RoundtripTestName"
    signal = MemorySignal(
        text=f"My name is {value}",
        signal_type="identity_fact",
        confidence=0.98,
        scope="user",
        metadata={
            "category": "identity",
            "attribute": "preferred_name",
            "normalized_value": value,
        },
    )
    retriever = PostgresProfileRecallRetriever()

    def query(tenant, user):
        return SimpleNamespace(
            text="What's my name?",
            tenant_id=str(tenant),
            user_id=str(user),
            top_k=1,
            conversation_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
        )

    try:
        # Insert an independently consented event through the real transaction
        # boundary. Profile projection requires this committed event provenance.
        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            session.add(
                MemoryEvent(
                    event_id=event_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    source_type="integration_test",
                    payload_hash=uuid.uuid4().hex,
                    event_type="assertion",
                    payload={"text": signal.text},
                    consent_state="granted",
                )
            )

        projector = PostgresDerivedMemoryProjector(projection_manager=None)
        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            await projector._project_profile_fact(
                session=session,
                tenant_uuid=tenant_id,
                user_uuid=user_id,
                event_uuid=event_id,
                signal=signal,
                confidence=0.98,
                source_type="integration_test",
                source_ref=None,
                metadata=dict(signal.metadata),
            )

        # Separate transactions and conversation/session IDs: real read-after-write.
        found = await retriever.recall(query(tenant_id, user_id))
        assert len(found) == 1
        assert found[0].content == f"preferred_name: {value}"

        assert await retriever.recall(query(tenant_id, other_user)) == []
        assert await retriever.recall(query(other_tenant, user_id)) == []

        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            event = (
                await session.execute(select(MemoryEvent).where(MemoryEvent.event_id == event_id))
            ).scalar_one()
            event.consent_state = "revoked"

        assert await retriever.recall(query(tenant_id, user_id)) == []
    finally:
        # Only delete rows created by this test. Do not touch user-owned records.
        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            await session.execute(delete(ProfileFact).where(ProfileFact.event_id == event_id))
            await session.execute(delete(MemoryEvent).where(MemoryEvent.event_id == event_id))
