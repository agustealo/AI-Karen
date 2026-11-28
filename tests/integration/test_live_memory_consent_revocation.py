"""Live PostgreSQL regression: revoked consent must block all durable recall paths.

Exercises the exact production SQL predicates before LIMIT, with real scoped
events, assertions and profile projections, not mocked queries.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

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
    public_generic, private_generic = uuid.uuid4(), uuid.uuid4()
    event_ids = (public_event, private_event, public_generic, private_generic)
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
                # Flush the FK parent before adding the assertion or projection.
                await session.flush()
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
            # Independent generic memories exercise the assertion lane under
            # the same consent scopes without bypassing profile ownership.
            for event_id, scope in (
                (public_generic, "memory.write"), (private_generic, "private"),
            ):
                content = "favorite artist research notes " + scope
                session.add(MemoryEvent(
                    event_id=event_id, tenant_id=tenant_id, user_id=user_id,
                    source_type="chat_user", payload_hash=uuid.uuid4().hex,
                    event_type="memory_persisted", consent_state="granted",
                    payload={"content": content, "vault": {"consent_scope": scope}},
                ))
                await session.flush()
                session.add(MemoryAssertion(
                    event_id=event_id, tenant_id=tenant_id, user_id=user_id,
                    content=content, consent_state="granted",
                ))
            session.add(ConsentScope(
                scope_id=scope_id, tenant_id=tenant_id, user_id=user_id,
                scope_name="private", is_granted=True,
            ))
        expected_profile = {str(public_event), str(private_event)}
        expected_generic = {str(public_generic), str(private_generic)}
        expected_both = expected_profile | expected_generic
        assert await snapshot() == (
            expected_profile, expected_generic, expected_both,
        )

        # The event's historical consent_state remains granted. A *later*
        # user-level revocation must override that original grant immediately.
        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            record = (await session.execute(select(ConsentScope).where(
                ConsentScope.scope_id == scope_id,
            ))).scalar_one()
            record.is_granted = False
            record.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)

        assert await snapshot() == (
            {str(public_event)}, {str(public_generic)},
            {str(public_event), str(public_generic)},
        )

        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            record = (await session.execute(select(ConsentScope).where(
                ConsentScope.scope_id == scope_id,
            ))).scalar_one()
            record.is_granted = True
            record.revoked_at = None

        assert await snapshot() == (
            expected_profile, expected_generic, expected_both,
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


async def test_vault_export_and_tombstone_respect_monotonic_revocation() -> None:
    from dataclasses import replace

    from ai_karen_engine.core.memory.protocols import VaultContext
    from ai_karen_engine.core.memory.types import MemoryEntry, MemoryMetadata
    from ai_karen_engine.platform.memory.postgres.vault import (
        NeuroVaultAuthorizationError, PostgresNeuroVault,
    )

    tenant, user, event_id, assertion_id = (uuid.uuid4() for _ in range(4))
    scope_id = uuid.uuid4()
    scope = f"vault-revocation-{scope_id}"
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    earlier = now - timedelta(days=2)
    context = VaultContext(
        tenant_id=str(tenant), user_id=str(user),
        request_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()),
        policy_context={
            "memory_read_authorized": True, "memory_delete_authorized": True,
            "memory_write_authorized": True,
        },
    )
    vault = PostgresNeuroVault()
    ids = [str(assertion_id)]
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(ConsentScope(
                scope_id=scope_id, tenant_id=tenant, user_id=user,
                scope_name=scope, is_granted=True,
            ))
            session.add(MemoryEvent(
                event_id=event_id, tenant_id=tenant, user_id=user,
                source_type="chat_user", payload_hash=uuid.uuid4().hex,
                event_type="memory_persisted", consent_state="granted",
                valid_from=earlier - timedelta(days=1),
                payload={"content": "private fact", "vault": {"consent_scope": scope}},
            ))
            await session.flush()
            session.add(MemoryAssertion(
                assertion_id=assertion_id, event_id=event_id, tenant_id=tenant,
                user_id=user, content="private fact", consent_state="granted",
                valid_from=earlier - timedelta(days=1),
            ))
        assert [item.content for item in await vault.export(ids, context=context)] == ["private fact"]

        async def grant(value: bool) -> None:
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                row = (await session.execute(select(ConsentScope).where(
                    ConsentScope.scope_id == scope_id,
                ))).scalar_one()
                row.is_granted = value
                row.revoked_at = None if value else now

        await grant(False)
        assert await vault.export(ids, context=context) == []
        assert await vault.verify_integrity(ids, context=context) == {ids[0]: True}
        await grant(True)
        assert len(await vault.export(ids, context=context)) == 1

        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            event = (await session.execute(select(MemoryEvent).where(
                MemoryEvent.event_id == event_id,
            ))).scalar_one()
            assertion = (await session.execute(select(MemoryAssertion).where(
                MemoryAssertion.assertion_id == assertion_id,
            ))).scalar_one()
            event.valid_to = earlier
            assertion.valid_to = earlier

        for _ in range(2):
            receipt = await vault.tombstone(
                ids[0], reason="test expiry",
                context=replace(context, request_id=str(uuid.uuid4())),
            )
            assert receipt.persisted and receipt.tombstoned
            assert await vault.export(ids, context=context) == []
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                assert (await session.execute(select(MemoryEvent.valid_to).where(
                    MemoryEvent.event_id == event_id,
                ))).scalar_one() == earlier
                assert (await session.execute(select(MemoryAssertion.valid_to).where(
                    MemoryAssertion.assertion_id == assertion_id,
                ))).scalar_one() == earlier

        assert (await vault.delete(ids[0], reason="test delete", context=context)).persisted
        assert await vault.export(ids, context=context) == []
        assert await vault.verify_integrity(ids, context=context) == {ids[0]: False}
        replacement = MemoryEntry(
            id=ids[0], content="private fact",
            metadata=MemoryMetadata(
                tenant_id=str(tenant), user_id=str(user), source="chat_user",
                custom={"consent_scope": scope},
            ),
        )
        with pytest.raises(NeuroVaultAuthorizationError, match="retired memory identity"):
            await vault.persist(
                replacement, context=replace(context, request_id=str(uuid.uuid4())),
            )
        assert await vault.export(ids, context=context) == []
        assert await vault.verify_integrity(ids, context=context) == {ids[0]: False}
        # A genuinely new identity is not prohibited by an unrelated deletion.
        fresh = replace(replacement, id=str(uuid.uuid4()))
        fresh_context = replace(context, request_id=str(uuid.uuid4()))
        first = await vault.persist(fresh, context=fresh_context)
        assert first.persisted
        replay = await vault.persist(fresh, context=fresh_context)
        assert replay.persisted and replay.metadata["idempotent_replay"] is True
        assert replay.metadata["event_id"] == first.metadata["event_id"]

        # Revoking only the canonical event must also invalidate a replay
        # whose assertion row remains granted and current.
        fresh_event_id = uuid.UUID(first.metadata["event_id"])
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            fresh_event = (await session.execute(select(MemoryEvent).where(
                MemoryEvent.event_id == fresh_event_id,
            ))).scalar_one()
            fresh_event.consent_state = "revoked"
        with pytest.raises(NeuroVaultAuthorizationError, match="memory replay no longer authorized"):
            await vault.persist(fresh, context=fresh_context)
        assert await vault.export([fresh.id], context=context) == []
        assert await vault.verify_integrity([fresh.id], context=context) == {fresh.id: True}

        # Source validity is an independent boundary from the assertion.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            fresh_event = (await session.execute(select(MemoryEvent).where(
                MemoryEvent.event_id == fresh_event_id,
            ))).scalar_one()
            fresh_event.consent_state = "granted"
            fresh_event.valid_to = earlier
        with pytest.raises(NeuroVaultAuthorizationError, match="memory replay no longer authorized"):
            await vault.persist(fresh, context=fresh_context)
        assert await vault.export([fresh.id], context=context) == []
        foreign_context = replace(context, user_id=str(uuid.uuid4()))
        assert await vault.export([fresh.id], context=foreign_context) == []
        assert not (await vault.delete(fresh.id, reason="foreign principal", context=foreign_context)).persisted
        denied_context = replace(context, policy_context={"denied": True})
        with pytest.raises(NeuroVaultAuthorizationError):
            await vault.export([fresh.id], context=denied_context)
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            assert (await session.execute(select(MemoryEvent.valid_to).where(
                MemoryEvent.event_id == event_id,
            ))).scalar_one() == earlier
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(delete(MemoryAssertion).where(
                MemoryAssertion.tenant_id == tenant, MemoryAssertion.user_id == user,
            ))
            await session.execute(delete(MemoryEvent).where(
                MemoryEvent.tenant_id == tenant, MemoryEvent.user_id == user,
            ))
            await session.execute(delete(ConsentScope).where(ConsentScope.scope_id == scope_id))
