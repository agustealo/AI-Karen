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
    pytest.mark.asyncio,
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
