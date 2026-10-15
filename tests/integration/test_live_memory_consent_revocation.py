"""Live PostgreSQL regression: revoked consent must block all durable recall paths.

Exercises the exact production SQL predicates before LIMIT, with real scoped
events, assertions and profile projections, not mocked queries.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from ai_karen_engine.core.memory.types import MemoryQuery
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.event_source import PostgresEventSource
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    ConsentScope, MemoryAssertion, MemoryEvent, ProfileFact,
)
from ai_karen_engine.platform.memory.postgres.profile_retriever import (
    PostgresProfileRecallRetriever,
)
from ai_karen_engine.platform.memory.postgres.recall_retriever import PostgresRecallRetriever


pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1",
        reason="requires isolated migrated PostgreSQL memory test database",
    ),
]


async def test_later_scope_revocation_and_restoration_gate_every_recall_source():
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    public_event, private_event = uuid.uuid4(), uuid.uuid4()
    event_ids = (public_event, private_event)
    scope_id = uuid.uuid4()
    query = MemoryQuery(
        tenant_id=str(tenant_id),
        user_id=str(user_id),
        text="favorite artist",
        top_k=20,
    )

    async def snapshot():
        profile = await PostgresProfileRecallRetriever().recall(query)
        assertions = await PostgresRecallRetriever().recall(query)
        events = await PostgresEventSource().fetch_many(
            tenant_id=str(tenant_id), user_id=str(user_id),
            event_ids=[str(x) for x in event_ids],
        )
        profile_ids = {entry.metadata.custom["event_id"] for entry in profile}
        assertion_ids = {entry.metadata.custom["event_id"] for entry in assertions}
        return profile_ids, assertion_ids, set(events)

    try:
        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            for event_id, artist, scope in (
                (public_event, "Bob Marley", "memory.write"),
                (private_event, "Nina Simone", "private"),
            ):
                session.add(MemoryEvent(
                    event_id=event_id, tenant_id=tenant_id, user_id=user_id,
                    source_type="chat_user", payload_hash=uuid.uuid4().hex,
                    event_type="memory_persisted", consent_state="granted",
                    payload={
                        "content": f"My favorite artist is {artist}",
                        "vault": {"consent_scope": scope},
                    },
                ))
                session.add(MemoryAssertion(
                    event_id=event_id, tenant_id=tenant_id, user_id=user_id,
                    content=f"My favorite artist is {artist}",
                    consent_state="granted",
                ))
                session.add(ProfileFact(
                    event_id=event_id, tenant_id=tenant_id, user_id=user_id,
                    category="preference", attribute="favorite_artist",
                    source_type="chat_user",
                    value={"value": artist, "cardinality": "set"},
                ))
            session.add(ConsentScope(
                scope_id=scope_id, tenant_id=tenant_id, user_id=user_id,
                scope_name="private", is_granted=True,
            ))
        expected_both = {str(x) for x in event_ids}
        assert await snapshot() == (
            expected_both, expected_both, expected_both,
        )

        # The event's historical consent_state remains granted. A *later*
        # user-level revocation must override that original grant immediately.
        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            record = (await session.execute(select(ConsentScope).where(
                ConsentScope.scope_id == scope_id,
            ))).scalar_one()
            record.is_granted = False
            record.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)

        expected_public = {str(public_event)}
        assert await snapshot() == (
            expected_public, expected_public, expected_public,
        )

        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            record = (await session.execute(select(ConsentScope).where(
                ConsentScope.scope_id == scope_id,
            ))).scalar_one()
            record.is_granted = True
            record.revoked_at = None

        assert await snapshot() == (
            expected_both, expected_both, expected_both,
        )
        # Another tenant/user can never invoke this event source by UUID.
        assert not await PostgresEventSource().fetch_many(
            tenant_id=str(uuid.uuid4()), user_id=str(user_id),
            event_ids=[str(x) for x in event_ids],
        )
    finally:
        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            await session.execute(delete(ProfileFact).where(
                ProfileFact.event_id.in_(event_ids),
            ))
            await session.execute(delete(MemoryAssertion).where(
                MemoryAssertion.event_id.in_(event_ids),
            ))
            await session.execute(delete(MemoryEvent).where(
                MemoryEvent.event_id.in_(event_ids),
            ))
            await session.execute(delete(ConsentScope).where(
                ConsentScope.scope_id == scope_id,
            ))


async def test_recalled_event_without_vault_scope_uses_canonical_default_consent():
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    event_id, scope_id = uuid.uuid4(), uuid.uuid4()
    try:
        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            session.add(MemoryEvent(
                event_id=event_id, tenant_id=tenant_id, user_id=user_id,
                source_type="legacy_user", payload_hash=uuid.uuid4().hex,
                event_type="memory_persisted", consent_state="granted",
                payload={"content": "legacy-memory"},
            ))
            session.add(ConsentScope(
                scope_id=scope_id, tenant_id=tenant_id, user_id=user_id,
                scope_name="memory.write", is_granted=False,
            ))
        assert not await PostgresEventSource().fetch_many(
            tenant_id=str(tenant_id), user_id=str(user_id),
            event_ids=[str(event_id)],
        )
    finally:
        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            await session.execute(delete(MemoryEvent).where(
                MemoryEvent.event_id == event_id,
            ))
            await session.execute(delete(ConsentScope).where(
                ConsentScope.scope_id == scope_id,
            ))
