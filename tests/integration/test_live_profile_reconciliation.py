"""Live MI-04 dry-run, authorized apply, and idempotent legacy reconciliation."""

from __future__ import annotations

import os
import uuid

import asyncpg

import pytest
from sqlalchemy import delete, select

from ai_karen_engine.core.memory.protocols import VaultContext
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    ConsentScope, MemoryEvent, ProfileFact,
)
from ai_karen_engine.platform.memory.postgres.profile_reconciliation import (
    reconcile_profile_projection_lane,
)

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1",
        reason="requires opt-in isolated migrated PostgreSQL memory database",
    ),
]


def _payload(artist: str, *, consent_scope="memory.write") -> dict:
    return {
        "content": f"I love {artist}",
        "metadata": {"custom": {"signal_semantics": {
            "category": "preference",
            "attribute": "favorite_artist",
            "normalized_value": artist,
            "cardinality": "set", "domain": "music",
        }}},
        "vault": {"consent_scope": consent_scope},
    }


async def test_live_legacy_projection_reconciliation_is_safe_and_idempotent():
    tenant, user = uuid.uuid4(), uuid.uuid4()
    event_ids = [uuid.uuid4() for _ in range(5)]
    private_consent_id = uuid.uuid4()
    # The two Bob rows compete for the same SET member. Nina is a separate
    # member. A revoked event and a revoked consent scope must not be keyed.
    artists = [
        ("Bob Marley", "granted", "memory.write"),
        ("Bob Marley", "granted", "memory.write"),
        ("Nina Simone", "granted", "memory.write"),
        ("Duke Ellington", "revoked", "memory.write"),
        ("Ella Fitzgerald", "granted", "private"),
    ]
    context = VaultContext(
        tenant_id=str(tenant), user_id=str(user),
        actor_id="ci-memory-maintainer",
        request_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()),
        policy_context={
            "allowed_capabilities": ["memory.maintenance"],
            "authorized_tenant_id": str(tenant),
            "authorized_user_id": str(user),
        },
    )
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(ConsentScope(
                scope_id=private_consent_id, tenant_id=tenant, user_id=user,
                scope_name="private", is_granted=False,
            ))
            for event_id, (artist, consent, scope) in zip(event_ids, artists):
                session.add(MemoryEvent(
                    event_id=event_id, tenant_id=tenant, user_id=user,
                    source_type="chat_user", payload_hash=uuid.uuid4().hex,
                    event_type="memory_persisted", payload=_payload(artist, consent_scope=scope),
                    consent_state=consent,
                ))
                session.add(ProfileFact(
                    event_id=event_id, tenant_id=tenant, user_id=user,
                    category="preference", attribute="favorite_artist",
                    source_type="chat_user", value={
                        "value": artist, "text": f"I love {artist}",
                        "cardinality": "set", "domain": "music",
                    },
                    projection_key=None,
                ))

        dry = await reconcile_profile_projection_lane(
            context=context, category="preference",
            attribute="favorite_artist",
        )
        assert dry.dry_run
        assert dry.scanned == 5
        assert dry.eligible == 1
        assert dry.updated == 0
        assert dry.blocked == {
            "duplicate_current_slot": 2,
            "revoked_consent_scope": 1,
            "revoked_event": 1,
        }

        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            unmodified = (await session.execute(select(ProfileFact).where(
                ProfileFact.tenant_id == tenant, ProfileFact.user_id == user,
            ))).scalars().all()
            assert all(row.projection_key is None for row in unmodified)

        applied = await reconcile_profile_projection_lane(
            context=context, category="preference",
            attribute="favorite_artist", apply=True,
        )
        assert applied.updated == 1
        assert applied.blocked == dry.blocked

        again = await reconcile_profile_projection_lane(
            context=context, category="preference",
            attribute="favorite_artist", apply=True,
        )
        assert again.updated == 0
        assert again.eligible == 0
        assert again.blocked == dry.blocked

        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            rows = (await session.execute(select(ProfileFact).where(
                ProfileFact.tenant_id == tenant,
                ProfileFact.user_id == user,
            ))).scalars().all()
            assert len(rows) == 5
            keyed = [row for row in rows if row.projection_key is not None]
            assert len(keyed) == 1
            assert keyed[0].value["value"] == "Nina Simone"
            assert all(row.valid_to is None for row in rows)
            assert all(row.supersedes is None for row in rows)
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(delete(ProfileFact).where(
                ProfileFact.event_id.in_(event_ids),
            ))
            await session.execute(delete(MemoryEvent).where(
                MemoryEvent.event_id.in_(event_ids),
            ))
            await session.execute(delete(ConsentScope).where(
                ConsentScope.scope_id == private_consent_id,
            ))


async def test_live_reconciliation_rejects_oversized_scan_without_mutation():
    tenant, user = uuid.uuid4(), uuid.uuid4()
    ids = [uuid.uuid4(), uuid.uuid4()]
    context = VaultContext(
        tenant_id=str(tenant), user_id=str(user),
        actor_id="ci-memory-maintainer", request_id=str(uuid.uuid4()),
        correlation_id=str(uuid.uuid4()), policy_context={
            "allowed_capabilities": ["memory.maintenance"],
            "authorized_tenant_id": str(tenant),
            "authorized_user_id": str(user),
        },
    )
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            for event_id, artist in zip(ids, ("Bob Marley", "Nina Simone")):
                session.add(MemoryEvent(
                    event_id=event_id, tenant_id=tenant, user_id=user,
                    source_type="chat_user", payload_hash=uuid.uuid4().hex,
                    event_type="memory_persisted", payload=_payload(artist),
                ))
                session.add(ProfileFact(
                    event_id=event_id, tenant_id=tenant, user_id=user,
                    category="preference", attribute="favorite_artist",
                    source_type="chat_user",
                    value={"value": artist, "text": f"I love {artist}",
                           "cardinality": "set", "domain": "music"},
                ))

        with pytest.raises(ValueError, match="bounded scan"):
            await reconcile_profile_projection_lane(
                context=context, category="preference",
                attribute="favorite_artist", apply=True, max_rows=1,
            )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            facts = (await session.execute(select(ProfileFact).where(
                ProfileFact.event_id.in_(ids),
            ))).scalars().all()
            assert len(facts) == 2
            assert all(fact.projection_key is None for fact in facts)
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(delete(ProfileFact).where(
                ProfileFact.event_id.in_(ids),
            ))
            await session.execute(delete(MemoryEvent).where(
                MemoryEvent.event_id.in_(ids),
            ))


async def test_profile_fact_rls_blocks_cross_tenant_reads_with_unprivileged_role():
    """Exercise actual database RLS, not SQL text inspection or ORM filters."""
    tenant_a, tenant_b, user = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    event_a, event_b = uuid.uuid4(), uuid.uuid4()
    try:
        for tenant, event_id, artist in (
            (tenant_a, event_a, "Bob Marley"),
            (tenant_b, event_b, "Nina Simone"),
        ):
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                session.add(MemoryEvent(
                    event_id=event_id, tenant_id=tenant, user_id=user,
                    source_type="chat_user", payload_hash=uuid.uuid4().hex,
                    event_type="memory_persisted", payload=_payload(artist),
                ))
                session.add(ProfileFact(
                    event_id=event_id, tenant_id=tenant, user_id=user,
                    category="preference", attribute="favorite_artist",
                    source_type="chat_user",
                    value={"value": artist, "text": f"I love {artist}",
                           "cardinality": "set", "domain": "music"},
                ))

        connection = await asyncpg.connect(os.environ["DATABASE_URL"])
        try:
            async with connection.transaction():
                await connection.execute("SET LOCAL ROLE karen_ci_memory_reader")
                await connection.execute(
                    "SELECT set_config('app.current_tenant_id', $1, true)",
                    str(tenant_a),
                )
                found = await connection.fetch(
                    "SELECT event_id FROM public.profile_fact "
                    "WHERE event_id = ANY($1::uuid[])",
                    [event_a, event_b],
                )
                assert {item["event_id"] for item in found} == {event_a}
            async with connection.transaction():
                await connection.execute("SET LOCAL ROLE karen_ci_memory_reader")
                await connection.execute(
                    "SELECT set_config('app.current_tenant_id', $1, true)",
                    str(tenant_b),
                )
                found = await connection.fetch(
                    "SELECT event_id FROM public.profile_fact "
                    "WHERE event_id = ANY($1::uuid[])",
                    [event_a, event_b],
                )
                assert {item["event_id"] for item in found} == {event_b}
            async with connection.transaction():
                await connection.execute("SET LOCAL ROLE karen_ci_memory_reader")
                # No tenant setting is explicitly denied by the RLS policy.
                found = await connection.fetch(
                    "SELECT event_id FROM public.profile_fact "
                    "WHERE event_id = ANY($1::uuid[])",
                    [event_a, event_b],
                )
                assert found == []
        finally:
            await connection.close()
    finally:
        for tenant, event_id in ((tenant_a, event_a), (tenant_b, event_b)):
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                await session.execute(
                    delete(ProfileFact).where(ProfileFact.event_id == event_id)
                )
                await session.execute(
                    delete(MemoryEvent).where(MemoryEvent.event_id == event_id)
                )
