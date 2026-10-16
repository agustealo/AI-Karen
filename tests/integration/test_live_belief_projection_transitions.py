"""MI-07: real NeuroVault to PostgreSQL profile belief transitions.

Requires the isolated migrated CI PostgreSQL database. No mocked SQL,
session, permissions, profile projection or memory retriever.
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from ai_karen_engine.core.memory.formation.service import MemoryFormationService
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.derived_projector import (
    PostgresDerivedMemoryProjector,
)
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    MemoryAssertion, MemoryEpisode, MemoryEvent, ProfileFact, ProjectionStatus,
)
from ai_karen_engine.platform.memory.postgres.profile_retriever import (
    PostgresProfileRecallRetriever,
)
from ai_karen_engine.platform.memory.postgres.vault import PostgresNeuroVault

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1",
        reason="requires isolated migrated PostgreSQL memory database",
    ),
]


class _OnlyPostgres:
    async def project_event(self, event_data, assertion_data):
        # The governed database projection is real. Only unrelated external
        # Redis/graph runtime projections are intentionally disabled.
        return {}


async def test_live_reinforcement_conflict_correction_replay_and_revocation():
    tenant, user = uuid.uuid4(), uuid.uuid4()
    session_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    factory = lambda: async_transaction_scope(tenant_id=str(tenant))
    projector = PostgresDerivedMemoryProjector(projection_manager=_OnlyPostgres())
    formation = MemoryFormationService(
        vault_factory=lambda _tenant: PostgresNeuroVault(session_factory=factory),
        derived_projector=projector,
    )
    retriever = PostgresProfileRecallRetriever()
    query = SimpleNamespace(
        text="What's my favorite genre?",
        tenant_id=str(tenant), user_id=str(user),
        session_id=str(uuid.uuid4()),
        conversation_id=str(uuid.uuid4()), top_k=10,
    )

    async def write(text):
        result = await formation.process_interaction(
            text=text, tenant_id=str(tenant), user_id=str(user),
            source_type="chat_user", source_ref=conversation_id,
            session_id=session_id, conversation_id=conversation_id,
            actor_id=str(user), request_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            policy_context={
                "memory_write_authorized": True,
                "allowed_capabilities": ["memory.write"],
                "authorized_tenant_id": str(tenant),
                "authorized_user_id": str(user),
                "authorized_session_id": session_id,
            },
        )
        assert result["persisted"] == 1, result
        assert result.get("projection_failures", 0) == 0, result
        return result

    async def facts():
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            return (await session.execute(select(ProfileFact).where(
                ProfileFact.tenant_id == tenant,
                ProfileFact.user_id == user,
                ProfileFact.attribute == "favorite_genre",
            ).order_by(ProfileFact.created_at))).scalars().all()

    try:
        first = await write("My favorite genre is reggae.")
        original_id = first["receipts"][0]["event_id"]
        assert [item.content for item in await retriever.recall(query)] == [
            "favorite_genre: reggae"
        ]

        again = await write("My favorite genre is reggae.")
        current = await facts()
        assert len(current) == 1
        assert current[0].valid_to is None
        assert current[0].supersedes is None

        conflict = await write("My favorite genre is jazz.")
        current = await facts()
        assert len(current) == 1
        assert current[0].value["value"] == "reggae"
        assert current[0].value["belief_status"] == "disputed"
        # The current projection cannot masquerade as a verified favorite.
        assert await retriever.recall(query) == []

        # Neither old reinforcing nor quarantined event may replay against
        # the new current state after an explicit correction.
        corrected = await write("Actually my favorite genre is dancehall now.")
        current = await facts()
        assert len(current) == 2
        active = [row for row in current if row.valid_to is None]
        assert len(active) == 1
        assert active[0].value["value"] == "dancehall"
        assert "belief_status" not in active[0].value
        assert active[0].supersedes == next(
            row.fact_id for row in current if row.valid_to is not None
        )
        assert [item.content for item in await retriever.recall(query)] == [
            "favorite_genre: dancehall"
        ]

        # Reprocessing a historical event is idempotent even when it created
        # no new ProfileFact on its initial pass.
        for event in (again, conflict):
            await projector.project(
                tenant_id=str(tenant), user_id=str(user),
                event_id=event["receipts"][0]["event_id"],
                memory_id=event["receipts"][0]["memory_id"],
                signal=__import__(
                    "ai_karen_engine.core.memory.signals.semantic_classifier",
                    fromlist=["classify_explicit_user_memory"],
                ).classify_explicit_user_memory(
                    "My favorite genre is reggae." if event is again
                    else "My favorite genre is jazz."
                )[0],
                confidence=0.98, source_type="chat_user",
                source_ref=conversation_id,
                metadata={"session_id": session_id, "conversation_id": conversation_id},
            )
        assert [item.content for item in await retriever.recall(query)] == [
            "favorite_genre: dancehall"
        ]
        assert len(await facts()) == 2

        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            rows = (await session.execute(select(ProjectionStatus).where(
                ProjectionStatus.event_id.in_([
                    uuid.UUID(original_id),
                    uuid.UUID(again["receipts"][0]["event_id"]),
                    uuid.UUID(conflict["receipts"][0]["event_id"]),
                    uuid.UUID(corrected["receipts"][0]["event_id"]),
                ]),
                ProjectionStatus.target_store == "profile_belief",
            ))).scalars().all()
            assert len(rows) == 4
            assert all(row.status == "completed" for row in rows)

        assert await retriever.recall(SimpleNamespace(
            text=query.text, tenant_id=str(tenant), user_id=str(uuid.uuid4()),
            top_k=10,
        )) == []
        assert await retriever.recall(SimpleNamespace(
            text=query.text, tenant_id=str(uuid.uuid4()), user_id=str(user),
            top_k=10,
        )) == []
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            event_ids = select(MemoryEvent.event_id).where(
                MemoryEvent.tenant_id == tenant, MemoryEvent.user_id == user,
            )
            for model in (ProjectionStatus, ProfileFact, MemoryEpisode, MemoryAssertion):
                await session.execute(delete(model).where(model.event_id.in_(event_ids)))
            await session.execute(delete(MemoryEvent).where(
                MemoryEvent.tenant_id == tenant, MemoryEvent.user_id == user,
            ))
