"""Disposable PostgreSQL proof for canonical profile source ACL and revocation.

KAREN_TEST_POSTGRES_MEMORY=1 pytest tests/integration/test_live_profile_source_revocation.py -q

Only run on a migrated isolated test database.
"""
import os
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, update

from ai_karen_engine.core.memory.retrieval.neuro_recall import (
    NeuroRecall, RecallRequest,
)
from ai_karen_engine.core.memory.signals import MemorySignal
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.derived_projector import (
    PostgresDerivedMemoryProjector,
)
from ai_karen_engine.platform.memory.postgres.ledger_models import MemoryEvent, ProfileFact
from ai_karen_engine.platform.memory.postgres.profile_retriever import (
    PostgresProfileRecallRetriever,
)


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1",
        reason="Requires isolated migrated PostgreSQL test database",
    ),
]


async def test_profile_projection_canonical_source_and_live_revocation():
    tenant, user, other_tenant, other_user = (
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    )
    event_id = uuid.uuid4()
    source_ref = f"web-source-{uuid.uuid4().hex}"
    name = f"ProfileRevocation{uuid.uuid4().hex[:8]}"
    signal = MemorySignal(
        text=f"My name is {name}",
        signal_type="identity_fact",
        confidence=0.99,
        scope="user",
        metadata={
            "category": "identity",
            "attribute": "preferred_name",
            "normalized_value": name,
        },
    )
    retriever = PostgresProfileRecallRetriever()
    request = RecallRequest(
        query="What's my name?", tenant_id=str(tenant), user_id=str(user),
    )

    class _SourcePermission:
        active = True
        checked = []

        async def authorize(self, entry, recall_request):
            receipt = entry.metadata.custom["provenance"]
            self.checked.append((receipt["source_type"], receipt["source_ref"]))
            return (
                self.active
                and recall_request.tenant_id == str(tenant)
                and recall_request.user_id == str(user)
                and receipt["source_type"] == "web"
                and receipt["source_ref"] == source_ref
            )

    verifier = _SourcePermission()
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(MemoryEvent(
                event_id=event_id,
                tenant_id=tenant,
                user_id=user,
                source_type="web",
                source_ref=source_ref,
                payload_hash=uuid.uuid4().hex,
                event_type="assertion",
                payload={"text": signal.text},
                consent_state="granted",
            ))
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await PostgresDerivedMemoryProjector(
                projection_manager=None
            )._project_profile_fact(
                session=session, tenant_uuid=tenant, user_uuid=user,
                event_uuid=event_id, signal=signal, confidence=0.99,
                source_type="web", source_ref=source_ref,
                metadata=dict(signal.metadata),
            )

        raw = await retriever.recall(SimpleNamespace(
            text=request.query, tenant_id=str(tenant), user_id=str(user),
            top_k=10, conversation_id=None, session_id=None,
        ))
        matched = [entry for entry in raw if entry.metadata.custom["event_id"] == str(event_id)]
        assert len(matched) == 1
        assert matched[0].metadata.custom["provenance"]["source_ref"] == source_ref
        assert matched[0].metadata.custom["provenance"]["source_type"] == "web"

        # PostgreSQL consent and identity isolation are separate from live ACL.
        assert not await retriever.recall(SimpleNamespace(
            text=request.query, tenant_id=str(other_tenant), user_id=str(user),
            top_k=10, conversation_id=None, session_id=None,
        ))
        assert not await retriever.recall(SimpleNamespace(
            text=request.query, tenant_id=str(tenant), user_id=str(other_user),
            top_k=10, conversation_id=None, session_id=None,
        ))
        denied = await NeuroRecall(retriever).recall(request)
        assert all(entry.id != matched[0].id for entry in denied.memories)
        recall = NeuroRecall(retriever, source_authorizer=verifier)
        allowed = await recall.recall(request)
        assert any(entry.id == matched[0].id for entry in allowed.memories)
        verifier.active = False
        revoked = await recall.recall(request)
        assert all(entry.id != matched[0].id for entry in revoked.memories)
        assert verifier.checked == [("web", source_ref), ("web", source_ref)]

        # Even a forged projection source cannot change the canonical event.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(
                update(ProfileFact)
                .where(ProfileFact.event_id == event_id)
                .values(source_type="chat_user", source_ref="forged-message")
            )
        assert all(
            entry.metadata.custom["event_id"] != str(event_id)
            for entry in await retriever.recall(SimpleNamespace(
                text=request.query, tenant_id=str(tenant), user_id=str(user),
                top_k=10, conversation_id=None, session_id=None,
            ))
        )
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(delete(ProfileFact).where(ProfileFact.event_id == event_id))
            await session.execute(delete(MemoryEvent).where(MemoryEvent.event_id == event_id))
