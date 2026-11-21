"""Real PostgreSQL proof for derived memory source revocation.

KAREN_TEST_POSTGRES_MEMORY=1 pytest tests/integration/test_live_derived_projection_source_revocation.py -q
Run only against an isolated migrated disposable database.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import delete, update

from ai_karen_engine.core.memory.retrieval.neuro_recall import NeuroRecall, RecallRequest
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    MemoryEvent, MemoryOpenLoop, MemoryProspectiveItem, MemoryUserGoal,
)
from ai_karen_engine.platform.memory.postgres.procedural_models import MemoryProcedure
from ai_karen_engine.platform.memory.postgres.procedural_retriever import (
    PostgresProceduralRecallRetriever,
)
from ai_karen_engine.platform.memory.postgres.user_state_retriever import (
    PostgresUserStateRecallRetriever,
)


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1",
        reason="Requires isolated migrated PostgreSQL",
    ),
]


async def test_derived_projection_recall_live_acl_and_consent_revocation():
    tenant, user, other_tenant, other_user = (
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    )
    event_ids = [uuid.uuid4() for _ in range(8)]
    source_ref = f"web-document-{uuid.uuid4().hex}"
    kinds = ("procedure", "goal", "open_loop", "prospective")
    expected_external: set[str] = set()
    expected_direct: set[str] = set()

    class _LiveACL:
        active = True
        calls = 0

        async def authorize(self, entry, request):
            self.calls += 1
            provenance = entry.metadata.custom["provenance"]
            return (
                self.active
                and request.tenant_id == str(tenant)
                and request.user_id == str(user)
                and provenance["source_type"] == "web"
                and provenance["source_ref"] == source_ref
            )

    acl = _LiveACL()
    retrievers = (
        PostgresProceduralRecallRetriever(),
        PostgresUserStateRecallRetriever(),
    )
    request = RecallRequest(
        query="goal workflow unfinished upcoming", tenant_id=str(tenant),
        user_id=str(user), top_k=30, latency_budget_ms=5000,
    )
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            for i, kind in enumerate(kinds):
                for external in (False, True):
                    idx = i * 2 + int(external)
                    event_id = event_ids[idx]
                    origin = "web" if external else "chat_user"
                    ref = source_ref if external else f"conversation-{idx}"
                    session.add(MemoryEvent(
                        event_id=event_id, tenant_id=tenant, user_id=user,
                        source_type=origin, source_ref=ref,
                        payload_hash=uuid.uuid4().hex,
                        event_type="memory_persisted",
                        payload={"text": "workflow goal unfinished upcoming"},
                        consent_state="granted",
                    ))
                    await session.flush()
                    projection_id = uuid.uuid4()
                    if kind == "procedure":
                        item = MemoryProcedure(
                            procedure_id=projection_id, source_event_id=event_id,
                            tenant_id=tenant, user_id=user, name="workflow procedure",
                            trigger_patterns=["workflow"], tool_sequence=["review"],
                            lifecycle_state="active", confidence=0.98,
                        )
                    elif kind == "goal":
                        item = MemoryUserGoal(
                            goal_id=projection_id, event_id=event_id,
                            tenant_id=tenant, user_id=user, description="goal workflow",
                            goal_type="explicit", lifecycle_state="active",
                            confidence=0.98, source_type=origin, source_ref=ref,
                        )
                    elif kind == "open_loop":
                        item = MemoryOpenLoop(
                            open_loop_id=projection_id, event_id=event_id,
                            tenant_id=tenant, user_id=user,
                            description="unfinished workflow",
                            lifecycle_state="open", confidence=0.98,
                            source_type=origin, source_ref=ref,
                        )
                    else:
                        item = MemoryProspectiveItem(
                            prospective_id=projection_id, event_id=event_id,
                            tenant_id=tenant, user_id=user, event_type="workflow",
                            description="upcoming workflow",
                            lifecycle_state="ready", confidence=0.98,
                            source_type=origin, source_ref=ref,
                        )
                    session.add(item)
                    (expected_external if external else expected_direct).add(str(projection_id))

        gate = NeuroRecall(retrievers=retrievers, source_authorizer=acl)
        denied_by_default = await NeuroRecall(retrievers=retrievers).recall(request)
        assert not (expected_external & {item.id for item in denied_by_default.memories})
        assert expected_direct <= {item.id for item in denied_by_default.memories}
        granted = await gate.recall(request)
        assert expected_external | expected_direct <= {item.id for item in granted.memories}
        acl.active = False
        revoked = await gate.recall(request)
        assert not (expected_external & {item.id for item in revoked.memories})
        assert expected_direct <= {item.id for item in revoked.memories}
        assert acl.calls >= 8

        for t, u in ((other_tenant, user), (tenant, other_user)):
            other = await NeuroRecall(retrievers=retrievers).recall(RecallRequest(
                query=request.query, tenant_id=str(t), user_id=str(u),
                latency_budget_ms=5000,
            ))
            assert not ((expected_external | expected_direct) & {item.id for item in other.memories})

        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(
                update(MemoryEvent)
                .where(MemoryEvent.event_id.in_(event_ids))
                .values(consent_state="revoked")
            )
        consent_revoked = await gate.recall(request)
        assert not ((expected_external | expected_direct) & {
            item.id for item in consent_revoked.memories
        })
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            for cls, key in (
                (MemoryProcedure, MemoryProcedure.source_event_id),
                (MemoryUserGoal, MemoryUserGoal.event_id),
                (MemoryOpenLoop, MemoryOpenLoop.event_id),
                (MemoryProspectiveItem, MemoryProspectiveItem.event_id),
            ):
                await session.execute(delete(cls).where(key.in_(event_ids)))
            await session.execute(delete(MemoryEvent).where(MemoryEvent.event_id.in_(event_ids)))
