"""Disposable PostgreSQL persona attribution, recall and revocation proof."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from ai_karen_engine.core.memory.types import MemoryQuery
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    ConsentScope, MemoryAssertion, MemoryEvent,
)
from ai_karen_engine.platform.memory.postgres.recall_retriever import PostgresRecallRetriever

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1",
        reason="requires disposable PostgreSQL ledger",
    ),
]


async def test_persona_ledger_provenance_consent_and_tenant_scope():
    tenant, user, other_tenant = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    events = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    consent_id = uuid.uuid4()
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            for event_id, persona in zip(events, ("assistant", "expert", None)):
                session.add(MemoryEvent(
                    event_id=event_id, tenant_id=tenant, user_id=user,
                    source_type="chat_user", payload_hash=uuid.uuid4().hex,
                    event_type="memory_persisted", consent_state="granted",
                    payload={
                        "metadata": {"custom": {"persona_id": persona} if persona else {}},
                        "vault": {"consent_scope": "persona-proof"},
                    },
                ))
                await session.flush()
                session.add(MemoryAssertion(
                    event_id=event_id, tenant_id=tenant, user_id=user,
                    content="Shared recall probe", consent_state="granted",
                ))
            session.add(ConsentScope(
                scope_id=consent_id, tenant_id=tenant, user_id=user,
                scope_name="persona-proof", is_granted=True,
            ))

        query = MemoryQuery(
            text="Shared recall probe", tenant_id=str(tenant), user_id=str(user), top_k=10,
        )
        retriever = PostgresRecallRetriever()
        entries = await retriever.recall(query)
        assert len(entries) == 3
        persona_by_event = {
            entry.metadata.custom["event_id"]: entry.metadata.custom.get("persona_id")
            for entry in entries
        }
        assert persona_by_event[str(events[0])] == "assistant"
        assert persona_by_event[str(events[1])] == "expert"
        assert persona_by_event[str(events[2])] is None

        cross_tenant = MemoryQuery(
            text=query.text, tenant_id=str(other_tenant), user_id=str(user), top_k=10,
        )
        assert await retriever.recall(cross_tenant) == []

        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            record = (await session.execute(select(ConsentScope).where(
                ConsentScope.scope_id == consent_id
            ))).scalar_one()
            record.is_granted = False
            record.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        assert await retriever.recall(query) == []
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(delete(MemoryAssertion).where(
                MemoryAssertion.event_id.in_(events)
            ))
            await session.execute(delete(MemoryEvent).where(
                MemoryEvent.event_id.in_(events)
            ))
            await session.execute(delete(ConsentScope).where(
                ConsentScope.scope_id == consent_id
            ))
