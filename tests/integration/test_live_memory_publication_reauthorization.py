"""Live source-record and canonical event consent proof before model dispatch."""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

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
            session.add(ProfileFact(
                fact_id=fact_id, event_id=event_id, tenant_id=tenant,
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
                _origin("profile_fact", fact_id, event_id, fact.updated_at),
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
            # Both independent sessions query the database concurrently
            # while the writer's consent update is still uncommitted.
            before_commit = await asyncio.wait_for(
                asyncio.gather(*(
                    authorizer.authorize_selected_records(
                        tenant_id=str(tenant), user_id=str(user),
                        origins=selected,
                    )
                    for authorizer in (gate, separate_gate)
                )),
                timeout=15,
            )
            assert before_commit == [True, True]
        finally:
            release.set()
            await asyncio.wait_for(writer_task, timeout=15)

        # Both fresh transactions must reject the now committed withdrawal.
        after_commit = await asyncio.wait_for(
            asyncio.gather(*(
                authorizer.authorize_selected_records(
                    tenant_id=str(tenant), user_id=str(user),
                    origins=selected,
                )
                for authorizer in (gate, separate_gate)
            )),
            timeout=15,
        )
        assert after_commit == [False, False]

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
                MemoryEvent.event_id == event_id,
            ))
            await session.execute(delete(ConsentScope).where(
                ConsentScope.scope_id == scope_id,
            ))
