"""PostgreSQL proof that distinct workers cannot create duplicate current slots.

Requires the isolated test database used by live-postgres-memory-proof.yml.
Do not run against production; no mocked database or session doubles here.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from ai_karen_engine.core.memory.semantic_contract import profile_projection_key
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    MemoryEvent,
    ProfileFact,
)


pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1",
        reason="requires isolated migrated PostgreSQL memory test database",
    ),
]


async def test_live_unique_current_slot_under_concurrent_writers():
    tenant, user = uuid.uuid4(), uuid.uuid4()
    first, second, third = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    event_ids = (first, second, third)

    async def add_fact(event_id, value, *, valid_to=None):
        projection_key = profile_projection_key(
            tenant_id=str(tenant),
            user_id=str(user),
            category="preference",
            attribute="favorite_color",
            value={"value": value, "cardinality": "singleton"},
            source_event_id=str(event_id),
        )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(
                ProfileFact(
                    event_id=event_id,
                    tenant_id=tenant,
                    user_id=user,
                    category="preference",
                    attribute="favorite_color",
                    value={"value": value, "cardinality": "singleton"},
                    source_type="integration_test",
                    projection_key=projection_key,
                    valid_to=valid_to,
                )
            )
            await session.flush()

    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            for event_id in event_ids:
                session.add(
                    MemoryEvent(
                        event_id=event_id,
                        tenant_id=tenant,
                        user_id=user,
                        source_type="integration_test",
                        payload_hash=uuid.uuid4().hex,
                        event_type="assertion",
                        payload={"evidence": str(event_id)},
                        consent_state="granted",
                    )
                )

        # Two independent SQL transactions race to claim the same singleton.
        results = await asyncio.gather(
            add_fact(first, "black"),
            add_fact(second, "green"),
            return_exceptions=True,
        )
        assert sum(result is None for result in results) == 1, results
        rejected = [result for result in results if isinstance(result, BaseException)]
        assert len(rejected) == 1
        assert isinstance(rejected[0], IntegrityError)

        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            current = (
                await session.execute(
                    select(ProfileFact).where(
                        ProfileFact.tenant_id == tenant,
                        ProfileFact.user_id == user,
                        ProfileFact.attribute == "favorite_color",
                        ProfileFact.valid_to.is_(None),
                    )
                )
            ).scalars().all()
            assert len(current) == 1
            assert current[0].projection_key is not None

            # Retiring a current row releases the slot for an updated fact.
            current[0].valid_to = current[0].valid_from

        await add_fact(third, "blue")
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            current = (
                await session.execute(
                    select(ProfileFact).where(
                        ProfileFact.tenant_id == tenant,
                        ProfileFact.user_id == user,
                        ProfileFact.valid_to.is_(None),
                        ProfileFact.attribute == "favorite_color",
                    )
                )
            ).scalars().all()
            assert len(current) == 1
            assert current[0].value["value"] == "blue"
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(
                delete(ProfileFact).where(ProfileFact.event_id.in_(event_ids))
            )
            await session.execute(
                delete(MemoryEvent).where(MemoryEvent.event_id.in_(event_ids))
            )


async def test_live_set_members_have_independent_current_slots():
    tenant, user = uuid.uuid4(), uuid.uuid4()
    first, second = uuid.uuid4(), uuid.uuid4()
    events = (first, second)
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            for event_id in events:
                session.add(
                    MemoryEvent(
                        event_id=event_id, tenant_id=tenant, user_id=user,
                        source_type="integration_test",
                        payload_hash=uuid.uuid4().hex,
                        event_type="assertion",
                        payload={"evidence": str(event_id)},
                        consent_state="granted",
                    )
                )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            for event_id, artist in ((first, "Bob Marley"), (second, "Nina Simone")):
                value = {
                    "value": artist, "cardinality": "set", "domain": "music",
                }
                session.add(
                    ProfileFact(
                        event_id=event_id, tenant_id=tenant, user_id=user,
                        category="preference", attribute="favorite_artist",
                        value=value, source_type="integration_test",
                        projection_key=profile_projection_key(
                            tenant_id=str(tenant), user_id=str(user),
                            category="preference", attribute="favorite_artist",
                            value=value, source_event_id=str(event_id),
                        ),
                    )
                )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            current = (
                await session.execute(
                    select(ProfileFact).where(
                        ProfileFact.tenant_id == tenant,
                        ProfileFact.user_id == user,
                        ProfileFact.attribute == "favorite_artist",
                        ProfileFact.valid_to.is_(None),
                    )
                )
            ).scalars().all()
            assert {row.value["value"] for row in current} == {
                "Bob Marley", "Nina Simone",
            }
            assert len({row.projection_key for row in current}) == 2
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(
                delete(ProfileFact).where(ProfileFact.event_id.in_(events))
            )
            await session.execute(
                delete(MemoryEvent).where(MemoryEvent.event_id.in_(events))
            )


async def test_live_profile_recall_filters_exact_project_scope_before_limit():
    """Real PostgreSQL/RLS proof that a global result cannot crowd scoped truth."""
    from ai_karen_engine.core.memory.types import MemoryQuery
    from ai_karen_engine.platform.memory.postgres.profile_retriever import (
        PostgresProfileRecallRetriever,
    )

    tenant, user = uuid.uuid4(), uuid.uuid4()
    event_ids = [uuid.uuid4() for _ in range(3)]
    values = (
        {"value": "Boston", "cardinality": "singleton"},
        {"value": "Detroit", "cardinality": "scoped_singleton", "project_id": 42},
        {"value": "Chicago", "cardinality": "scoped_singleton", "project_id": 99},
    )
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            for event_id, value in zip(event_ids, values):
                session.add(MemoryEvent(
                    event_id=event_id, tenant_id=tenant, user_id=user,
                    source_type="integration_test", payload_hash=uuid.uuid4().hex,
                    event_type="assertion", payload={"evidence": str(event_id)},
                    consent_state="granted",
                ))
                session.add(ProfileFact(
                    event_id=event_id, tenant_id=tenant, user_id=user,
                    category="identity", attribute="work_location",
                    value=value, source_type="integration_test",
                    projection_key=profile_projection_key(
                        tenant_id=str(tenant), user_id=str(user),
                        category="identity", attribute="work_location",
                        value=value, source_event_id=str(event_id),
                    ),
                ))
        query = MemoryQuery(
            text="Where do I work for project 42?",
            tenant_id=str(tenant), user_id=str(user), top_k=1,
        )
        found = await PostgresProfileRecallRetriever().recall(query)
        assert len(found) == 1
        assert found[0].content == "work_location: Detroit"
        assert found[0].metadata.custom["semantic_scope"]["project_id"] == 42

        missing = await PostgresProfileRecallRetriever().recall(
            MemoryQuery(
                text="Where do I work for project 777?",
                tenant_id=str(tenant), user_id=str(user), top_k=1,
            )
        )
        assert missing == []

        history = await PostgresProfileRecallRetriever().recall(
            MemoryQuery(
                text="Where do I work last year?",
                tenant_id=str(tenant), user_id=str(user), top_k=1,
            )
        )
        assert history == []
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(
                delete(ProfileFact).where(ProfileFact.event_id.in_(event_ids))
            )
            await session.execute(
                delete(MemoryEvent).where(MemoryEvent.event_id.in_(event_ids))
            )


async def test_live_open_relation_can_be_recalled_by_the_same_generic_attribute():
    """Real Postgres/RLS verification of generic semantic readback, not mock recall."""
    from ai_karen_engine.core.intelligence.profile_attribute import requested_profile_attribute
    from ai_karen_engine.core.memory.signals.semantic_classifier import classify_explicit_user_memory
    from ai_karen_engine.core.memory.types import MemoryQuery
    from ai_karen_engine.platform.memory.postgres.profile_retriever import (
        PostgresProfileRecallRetriever,
    )

    statement = "My reading ritual is green tea at sunrise."
    signals = [
        signal for signal in classify_explicit_user_memory(statement)
        if signal.metadata.get("source") == "explicit_open_relation"
    ]
    assert len(signals) == 1
    signal = signals[0]
    attribute = signal.metadata["attribute"]
    assert requested_profile_attribute("What is my reading ritual?") == attribute
    tenant, user, event = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    value = {"value": signal.metadata["normalized_value"], "cardinality": "singleton"}
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(MemoryEvent(
                event_id=event, tenant_id=tenant, user_id=user,
                source_type="integration_test", payload_hash=uuid.uuid4().hex,
                event_type="assertion", payload={"evidence": statement},
                consent_state="granted",
            ))
            session.add(ProfileFact(
                event_id=event, tenant_id=tenant, user_id=user,
                category="personal_relation", attribute=attribute,
                value=value, source_type="integration_test",
                projection_key=profile_projection_key(
                    tenant_id=str(tenant), user_id=str(user),
                    category="personal_relation", attribute=attribute,
                    value=value, source_event_id=str(event),
                ),
            ))

        recall = PostgresProfileRecallRetriever()
        found = await recall.recall(MemoryQuery(
            text="What is my reading ritual?",
            tenant_id=str(tenant), user_id=str(user), top_k=5,
        ))
        assert len(found) == 1
        assert found[0].content == (
            "personal_relation.reading_ritual: green tea at sunrise"
        )

        # Generic query activation must never substitute a neighboring fact
        # when the requested relationship has no current profile projection.
        missing_relation = await recall.recall(MemoryQuery(
            text="What is my lunch ritual?",
            tenant_id=str(tenant), user_id=str(user), top_k=5,
        ))
        assert missing_relation == []

        cross_user = await recall.recall(MemoryQuery(
            text="What is my reading ritual?",
            tenant_id=str(tenant), user_id=str(uuid.uuid4()), top_k=5,
        ))
        assert cross_user == []
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(delete(ProfileFact).where(ProfileFact.event_id == event))
            await session.execute(delete(MemoryEvent).where(MemoryEvent.event_id == event))
