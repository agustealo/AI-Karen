"""Live source-record and canonical event consent proof before model dispatch."""
from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.event_source import PostgresEventSource
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    ConsentScope, MemoryAssertion, MemoryEvent, ProfileFact,
)

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1",
        reason="requires isolated migrated PostgreSQL memory database",
    ),
]


def _origin(kind: str, record_id: uuid.UUID, event_id: uuid.UUID, revision):
    if revision.tzinfo is None:
        revision = revision.replace(tzinfo=timezone.utc)
    return {
        "record_type": kind,
        "record_id": str(record_id),
        "event_id": str(event_id),
        "record_updated_at": revision.astimezone(timezone.utc).isoformat(),
    }


async def test_live_record_revision_and_event_consent_gate_selected_source():
    tenant, user = uuid.uuid4(), uuid.uuid4()
    event_id, assertion_id, fact_id, scope_id = (
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    )
    profile_event_id = uuid.uuid4()
    gate = PostgresEventSource()
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(MemoryEvent(
                event_id=event_id, tenant_id=tenant, user_id=user,
                event_type="memory_persisted", source_type="chat_user",
                payload_hash=uuid.uuid4().hex, consent_state="granted",
                payload={
                    "content": "verified test memory",
                    "vault": {"consent_scope": "sensitive-test"},
                },
            ))
            await session.flush()
            session.add(MemoryAssertion(
                assertion_id=assertion_id, event_id=event_id,
                tenant_id=tenant, user_id=user,
                content="verified test memory", consent_state="granted",
            ))
            session.add(MemoryEvent(
                event_id=profile_event_id, tenant_id=tenant, user_id=user,
                event_type="memory_persisted", source_type="chat_user",
                payload_hash=uuid.uuid4().hex, consent_state="granted",
                payload={
                    "content": "My preferred theme is dark.",
                    "vault": {"consent_scope": "sensitive-test"},
                },
            ))
            await session.flush()
            session.add(ProfileFact(
                fact_id=fact_id, event_id=profile_event_id, tenant_id=tenant,
                user_id=user, category="preference", attribute="theme",
                value={"value": "dark"}, source_type="chat_user",
            ))
            session.add(ConsentScope(
                scope_id=scope_id, tenant_id=tenant, user_id=user,
                scope_name="sensitive-test", is_granted=True,
            ))
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            assertion = (await session.execute(select(MemoryAssertion).where(
                MemoryAssertion.assertion_id == assertion_id,
            ))).scalar_one()
            fact = (await session.execute(select(ProfileFact).where(
                ProfileFact.fact_id == fact_id,
            ))).scalar_one()
            selected = [
                _origin("memory_assertion", assertion_id, event_id, assertion.updated_at),
                _origin("profile_fact", fact_id, profile_event_id, fact.updated_at),
            ]

        assert await gate.authorize_selected_records(
            tenant_id=str(tenant), user_id=str(user), origins=selected,
        ) is True
        assert await gate.authorize_selected_records(
            tenant_id=str(uuid.uuid4()), user_id=str(user), origins=selected,
        ) is False
        assert await gate.authorize_selected_records(
            tenant_id=str(tenant), user_id=str(uuid.uuid4()), origins=selected,
        ) is False
        stale = [{**selected[0], "record_updated_at": "2020-01-01T00:00:00+00:00"}]
        assert await gate.authorize_selected_records(
            tenant_id=str(tenant), user_id=str(user), origins=stale,
        ) is False
        forged_link = [{**selected[0], "event_id": str(uuid.uuid4())}]
        assert await gate.authorize_selected_records(
            tenant_id=str(tenant), user_id=str(user), origins=forged_link,
        ) is False
        assert await gate.authorize_selected_records(
            tenant_id=str(tenant), user_id=str(user),
            origins=[{**selected[0], "record_updated_at": None}],
        ) is False

        # Hold a real revocation transaction open while two independent
        # authorizers read the last committed consent state. Event barriers
        # establish the ordering; no sleep or mocked database result is used.
        staged = asyncio.Event()
        release = asyncio.Event()

        async def commit_revocation_after_readers() -> None:
            async with async_transaction_scope(tenant_id=str(tenant)) as writer:
                scope = (await writer.execute(select(ConsentScope).where(
                    ConsentScope.scope_id == scope_id,
                ))).scalar_one()
                scope.is_granted = False
                scope.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await writer.flush()
                staged.set()
                await release.wait()

        writer_task = asyncio.create_task(commit_revocation_after_readers())
        try:
            await asyncio.wait_for(staged.wait(), timeout=15)
            separate_gate = PostgresEventSource()
            # Prove overlap at the database connection boundary, not
            # merely that two asyncio coroutines were scheduled. The writer
            # already holds one connection: this requires two additional
            # reader connections and fails if the pool cannot supply them.
            connected = asyncio.Event()
            release_readers = asyncio.Event()
            connections_acquired = 0

            @asynccontextmanager
            async def reader_transaction(*args, **kwargs):
                nonlocal connections_acquired
                async with async_transaction_scope(*args, **kwargs) as session:
                    await session.connection()
                    connections_acquired += 1
                    if connections_acquired == 2:
                        connected.set()
                    await release_readers.wait()
                    yield session

            # Bound the entire group, including SQL execution and commit.
            # A stalled query must not retain a reader or the writer lock.
            async with asyncio.timeout(15):
                with patch(
                    "ai_karen_engine.platform.memory.postgres.event_source."
                    "async_transaction_scope",
                    reader_transaction,
                ):
                    # TaskGroup drains both readers if either fails or the
                    # rendezvous times out, before the writer is released.
                    async with asyncio.TaskGroup() as readers:
                        first_reader = readers.create_task(
                            gate.authorize_selected_records(
                                tenant_id=str(tenant), user_id=str(user),
                                origins=selected,
                            )
                        )
                        second_reader = readers.create_task(
                            separate_gate.authorize_selected_records(
                                tenant_id=str(tenant), user_id=str(user),
                                origins=selected,
                            )
                        )
                        try:
                            await asyncio.wait_for(connected.wait(), timeout=15)
                            assert connections_acquired == 2
                        finally:
                            release_readers.set()
                    assert [first_reader.result(), second_reader.result()] == [
                        True, True,
                    ]
        finally:
            release.set()
            await asyncio.wait_for(writer_task, timeout=15)

        # Bound the entire postcommit query/transaction lifetime too.
        async with asyncio.timeout(15):
            async with asyncio.TaskGroup() as readers:
                first_reader = readers.create_task(
                    gate.authorize_selected_records(
                        tenant_id=str(tenant), user_id=str(user),
                        origins=selected,
                    )
                )
                second_reader = readers.create_task(
                    separate_gate.authorize_selected_records(
                        tenant_id=str(tenant), user_id=str(user),
                        origins=selected,
                    )
                )
        assert [first_reader.result(), second_reader.result()] == [
            False, False,
        ]

        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            scope = (await session.execute(select(ConsentScope).where(
                ConsentScope.scope_id == scope_id,
            ))).scalar_one()
            scope.is_granted = True
            scope.revoked_at = None
        assert await separate_gate.authorize_selected_records(
            tenant_id=str(tenant), user_id=str(user), origins=selected,
        ) is True

        # Scope withdrawal after selection blocks both active derived records.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            scope = (await session.execute(select(ConsentScope).where(
                ConsentScope.scope_id == scope_id,
            ))).scalar_one()
            scope.is_granted = False
            scope.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        assert await gate.authorize_selected_records(
            tenant_id=str(tenant), user_id=str(user), origins=selected,
        ) is False

        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            scope = (await session.execute(select(ConsentScope).where(
                ConsentScope.scope_id == scope_id,
            ))).scalar_one()
            scope.is_granted = True
            scope.revoked_at = None
        assert await gate.authorize_selected_records(
            tenant_id=str(tenant), user_id=str(user), origins=selected,
        ) is True

        # A previously selected generic assertion/event may acquire profile
        # ownership before dispatch. Its immutable revision and consent alone
        # can no longer authorize the alternate representation.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            event = (await session.execute(select(MemoryEvent).where(
                MemoryEvent.event_id == event_id,
            ))).scalar_one()
            raw_origin = _origin("memory_event", event_id, event_id, event.updated_at)
        assert await gate.authorize_selected_records(
            tenant_id=str(tenant), user_id=str(user), origins=[raw_origin],
        ) is True
        late_fact_id = uuid.uuid4()
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(ProfileFact(
                fact_id=late_fact_id, event_id=event_id, tenant_id=tenant,
                user_id=user, category="preference", attribute="late_theme",
                value={"value": "light"}, source_type="chat_user",
            ))
        try:
            assert await gate.authorize_selected_records(
                tenant_id=str(tenant), user_id=str(user), origins=[selected[0]],
            ) is False
            assert await gate.authorize_selected_records(
                tenant_id=str(tenant), user_id=str(user), origins=[raw_origin],
            ) is False
            assert await gate.authorize_selected_records(
                tenant_id=str(tenant), user_id=str(user), origins=[selected[1]],
            ) is True
        finally:
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                await session.execute(delete(ProfileFact).where(
                    ProfileFact.fact_id == late_fact_id,
                ))

        # Record tombstoning after the same selection must fail closed.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            assertion = (await session.execute(select(MemoryAssertion).where(
                MemoryAssertion.assertion_id == assertion_id,
            ))).scalar_one()
            assertion.valid_to = datetime.now(timezone.utc).replace(tzinfo=None)
        assert await gate.authorize_selected_records(
            tenant_id=str(tenant), user_id=str(user), origins=selected,
        ) is False
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(delete(ProfileFact).where(
                ProfileFact.fact_id == fact_id,
            ))
            await session.execute(delete(MemoryAssertion).where(
                MemoryAssertion.assertion_id == assertion_id,
            ))
            await session.execute(delete(MemoryEvent).where(
                MemoryEvent.event_id.in_((event_id, profile_event_id)),
            ))
            await session.execute(delete(ConsentScope).where(
                ConsentScope.scope_id == scope_id,
            ))
