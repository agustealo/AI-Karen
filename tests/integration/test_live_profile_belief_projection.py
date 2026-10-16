"""Live PostgreSQL proof: a later statement is not automatically a correction."""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from ai_karen_engine.core.memory.signals import MemorySignal
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.derived_projector import PostgresDerivedMemoryProjector
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    ConsentScope, MemoryEvent, ProfileFact,
)
from ai_karen_engine.platform.memory.postgres.profile_retriever import PostgresProfileRecallRetriever


pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1",
        reason="isolated migrated PostgreSQL memory test database required",
    ),
]


async def test_reinforcement_disagreement_explicit_correction_and_recall():
    tenant, user = uuid.uuid4(), uuid.uuid4()
    event_ids: list[uuid.UUID] = []
    consent_id = uuid.uuid4()
    projector = PostgresDerivedMemoryProjector(projection_manager=None)
    retriever = PostgresProfileRecallRetriever()

    async def state():
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            rows = (await session.execute(
                select(ProfileFact).where(
                    ProfileFact.tenant_id == tenant,
                    ProfileFact.user_id == user,
                    ProfileFact.attribute == "favorite_genre",
                ).order_by(ProfileFact.created_at, ProfileFact.fact_id)
            )).scalars().all()
            return rows

    async def observe(value: str, *, correction=False, modality="asserted"):
        event = uuid.uuid4()
        event_ids.append(event)
        statement = (
            f"Actually my favorite genre is {value} now."
            if correction else f"My favorite genre is {value}."
        )
        metadata = {
            "source": "explicit_semantic_rule",
            "explicit_user_statement": True,
            "category": "preference",
            "attribute": "favorite_genre",
            "normalized_value": value,
            "assertion_modality": modality,
            "explicit_correction": correction,
        }
        signal = MemorySignal(
            text=statement, signal_type="preference",
            confidence=0.98, metadata=metadata,
        )
        # The event is committed before this derived, rebuildable projection.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(MemoryEvent(
                event_id=event, tenant_id=tenant, user_id=user,
                source_type="chat_user", payload_hash=uuid.uuid4().hex,
                event_type="memory_persisted",
                payload={"content": statement,
                         "metadata": {"custom": {"signal_semantics": metadata}},
                         "vault": {"consent_scope": "memory.write"}},
                consent_state="granted",
            ))
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await projector._project_profile_fact(
                session=session, tenant_uuid=tenant, user_uuid=user,
                event_uuid=event, signal=signal, confidence=0.98,
                source_type="chat_user", source_ref=None,
                metadata=dict(metadata),
            )
        return event

    def query(*, acting_user=user):
        return SimpleNamespace(
            text="What's my favorite genre?",
            tenant_id=str(tenant), user_id=str(acting_user),
            top_k=5, session_id=str(uuid.uuid4()),
            conversation_id=str(uuid.uuid4()),
        )

    try:
        first = await observe("reggae")
        rows = await state()
        assert len(rows) == 1
        assert rows[0].value["belief_operation"] == "create"
        assert [x.content for x in await retriever.recall(query())] == [
            "favorite_genre: reggae",
        ]

        second = await observe("reggae")
        rows = await state()
        assert len(rows) == 2
        old = next(row for row in rows if row.event_id == first)
        refreshed = next(row for row in rows if row.event_id == second)
        assert old.valid_to is not None
        assert refreshed.valid_to is None
        assert refreshed.value["belief_operation"] == "reinforce"
        assert refreshed.supersedes == old.fact_id

        conflicting = await observe("jazz")
        rows = await state()
        assert len(rows) == 2, "conflicting evidence must not become an active fact"
        assert all(row.event_id != conflicting for row in rows)
        assert [x.content for x in await retriever.recall(query())] == [
            "favorite_genre: reggae",
        ]
        # Quarantine does not delete or pretend the new committed evidence
        # did not exist: the canonical source event remains available.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            conflict_event = (await session.execute(
                select(MemoryEvent).where(MemoryEvent.event_id == conflicting)
            )).scalar_one()
            assert conflict_event.payload["content"] == "My favorite genre is jazz."

        corrected = await observe("dancehall", correction=True)
        rows = await state()
        active = [row for row in rows if row.valid_to is None]
        assert len(active) == 1
        assert active[0].event_id == corrected
        assert active[0].value["belief_operation"] == "supersede"
        assert active[0].supersedes == refreshed.fact_id
        assert [x.content for x in await retriever.recall(query())] == [
            "favorite_genre: dancehall",
        ]
        # Replaying the exact event must not create duplicate current slots.
        replay = MemorySignal(
            text="Actually my favorite genre is dancehall now.",
            signal_type="preference", confidence=0.98,
            metadata={
                "source": "explicit_semantic_rule",
                "category": "preference", "attribute": "favorite_genre",
                "normalized_value": "dancehall",
                "explicit_correction": True,
            },
        )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await projector._project_profile_fact(
                session=session, tenant_uuid=tenant, user_uuid=user,
                event_uuid=corrected, signal=replay, confidence=0.98,
                source_type="chat_user", source_ref=None,
                metadata=dict(replay.metadata),
            )
        assert len(await state()) == 3

        assert await retriever.recall(query(acting_user=uuid.uuid4())) == []

        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(ConsentScope(
                scope_id=consent_id, tenant_id=tenant, user_id=user,
                scope_name="memory.write", is_granted=False,
            ))
        assert await retriever.recall(query()) == []
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(delete(ProfileFact).where(
                ProfileFact.event_id.in_(event_ids)
            ))
            await session.execute(delete(MemoryEvent).where(
                MemoryEvent.event_id.in_(event_ids)
            ))
            await session.execute(delete(ConsentScope).where(
                ConsentScope.scope_id == consent_id
            ))


async def test_distinct_favorite_categories_are_independent():
    tenant, user = uuid.uuid4(), uuid.uuid4()
    events = [uuid.uuid4(), uuid.uuid4()]
    projector = PostgresDerivedMemoryProjector(projection_manager=None)
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            for event_id in events:
                session.add(MemoryEvent(
                    event_id=event_id, tenant_id=tenant, user_id=user,
                    source_type="chat_user", payload_hash=uuid.uuid4().hex,
                    event_type="memory_persisted", payload={"event_id": str(event_id)},
                    consent_state="granted",
                ))
        for event_id, attribute, value in (
            (events[0], "favorite_food", "jerk chicken"),
            (events[1], "favorite_genre", "reggae"),
        ):
            signal = MemorySignal(
                text=f"My {attribute} is {value}",
                signal_type="preference", confidence=0.98,
                metadata={"category": "preference",
                          "attribute": attribute, "normalized_value": value},
            )
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                await projector._project_profile_fact(
                    session=session, tenant_uuid=tenant, user_uuid=user,
                    event_uuid=event_id, signal=signal, confidence=0.98,
                    source_type="chat_user", source_ref=None,
                    metadata=dict(signal.metadata),
                )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            rows = (await session.execute(select(ProfileFact).where(
                ProfileFact.event_id.in_(events),
                ProfileFact.valid_to.is_(None),
            ))).scalars().all()
            assert {r.attribute for r in rows} == {
                "favorite_food", "favorite_genre",
            }
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(delete(ProfileFact).where(
                ProfileFact.event_id.in_(events)
            ))
            await session.execute(delete(MemoryEvent).where(
                MemoryEvent.event_id.in_(events)
            ))
