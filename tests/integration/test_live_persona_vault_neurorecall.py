"""Real NeuroVault -> PostgreSQL -> NeuroRecall persona lifecycle proof."""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import delete, select

from ai_karen_engine.core.memory.protocols import VaultContext
from ai_karen_engine.core.memory.retrieval.neuro_recall import NeuroRecall, RecallRequest
from ai_karen_engine.core.memory.types import (
    MemoryEntry, MemoryMetadata, MemoryNamespace, MemoryType,
)
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    ConsentScope, MemoryAssertion, MemoryEvent,
)
from ai_karen_engine.platform.memory.postgres.recall_retriever import PostgresRecallRetriever
from ai_karen_engine.platform.memory.postgres.vault import PostgresNeuroVault

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1",
        reason="requires disposable PostgreSQL memory database",
    ),
]


async def test_vault_to_recall_persona_filter_and_revocation():
    tenant, user = uuid.uuid4(), uuid.uuid4()
    consent_id = uuid.uuid4()
    ids = [uuid.uuid4() for _ in range(3)]
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(ConsentScope(
                scope_id=consent_id, tenant_id=tenant, user_id=user,
                scope_name="persona-proof", is_granted=True,
            ))

        vault = PostgresNeuroVault()
        context = VaultContext(
            tenant_id=str(tenant), user_id=str(user),
            request_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()),
            actor_id=str(user), policy_context={"memory_write_authorized": True},
        )
        for memory_id, persona in zip(ids, ("assistant", "expert", None)):
            custom = {"consent_scope": "persona-proof"}
            if persona:
                custom["persona_id"] = persona
            entry = MemoryEntry(
                id=str(memory_id), content="Persona durable lifecycle proof",
                memory_type=MemoryType.SEMANTIC, namespace=MemoryNamespace.LONG_TERM,
                metadata=MemoryMetadata(
                    tenant_id=str(tenant), user_id=str(user),
                    source="chat_user", custom=custom,
                ),
            )
            receipt = await vault.persist(entry, context=context)
            assert receipt.persisted

        recall = NeuroRecall(retriever=PostgresRecallRetriever())
        base = dict(query="Persona durable lifecycle proof",
                    tenant_id=str(tenant), user_id=str(user), top_k=10)
        unfiltered = await recall.recall(RecallRequest(**base))
        assert {str(item.id) for item in unfiltered.memories} == {str(i) for i in ids}

        assistant = await recall.recall(RecallRequest(
            **base, metadata={"persona_filter": "assistant"},
        ))
        assert {str(item.id) for item in assistant.memories} == {str(ids[0]), str(ids[2])}

        expert = await recall.recall(RecallRequest(
            **base, metadata={"persona_filter": "expert"},
        ))
        assert {str(item.id) for item in expert.memories} == {str(ids[1]), str(ids[2])}

        other_tenant = await recall.recall(RecallRequest(
            query=base["query"], tenant_id=str(uuid.uuid4()),
            user_id=str(user), top_k=10,
        ))
        assert not other_tenant.memories

        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            scope = (await session.execute(
                select(ConsentScope).where(ConsentScope.scope_id == consent_id)
            )).scalar_one()
            scope.is_granted = False
        revoked = await recall.recall(RecallRequest(**base))
        assert not revoked.memories
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            event_ids = (await session.execute(
                select(MemoryAssertion.event_id).where(
                    MemoryAssertion.assertion_id.in_(ids)
                )
            )).scalars().all()
            await session.execute(delete(MemoryAssertion).where(MemoryAssertion.assertion_id.in_(ids)))
            if event_ids:
                await session.execute(delete(MemoryEvent).where(MemoryEvent.event_id.in_(event_ids)))
            await session.execute(delete(ConsentScope).where(ConsentScope.scope_id == consent_id))
