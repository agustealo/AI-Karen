"""Cross-process consent revocation proof against the canonical PostgreSQL ledger."""
from __future__ import annotations

import asyncio
import multiprocessing
import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.event_source import PostgresEventSource
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    ConsentScope,
    MemoryAssertion,
    MemoryEvent,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1",
        reason="requires isolated migrated PostgreSQL memory database",
    ),
]


def _worker(tenant: str, user: str, origin: dict, ready, release, result) -> None:
    """Use a fresh interpreter and DB pool, never an inherited parent session."""
    async def run() -> None:
        gate = PostgresEventSource()
        before = await gate.authorize_selected_records(
            tenant_id=tenant, user_id=user, origins=[origin],
        )
        ready.put((os.getpid(), before))
        if not release.wait(25):
            raise TimeoutError("parent did not release cross-process reader")
        after = await gate.authorize_selected_records(
            tenant_id=tenant, user_id=user, origins=[origin],
        )
        wrong_tenant = await gate.authorize_selected_records(
            tenant_id=str(uuid.uuid4()), user_id=user, origins=[origin],
        )
        result.put((os.getpid(), after, wrong_tenant))

    try:
        asyncio.run(run())
    except BaseException as exc:
        result.put((os.getpid(), "error", type(exc).__name__, str(exc)))


@pytest.mark.timeout(90)
async def test_committed_revocation_visible_across_independent_processes():
    tenant, user = uuid.uuid4(), uuid.uuid4()
    event_id, assertion_id, scope_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    scope_name = f"cross-process-revocation-{uuid.uuid4().hex}"
    context = multiprocessing.get_context("spawn")
    ready, result, release = context.Queue(), context.Queue(), context.Event()
    workers = []

    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(MemoryEvent(
                event_id=event_id, tenant_id=tenant, user_id=user,
                event_type="memory_persisted", source_type="chat_user",
                payload_hash=uuid.uuid4().hex, consent_state="granted",
                payload={"content": "cross-process proof", "vault": {
                    "consent_scope": scope_name,
                }},
            ))
            await session.flush()
            session.add(MemoryAssertion(
                assertion_id=assertion_id, event_id=event_id,
                tenant_id=tenant, user_id=user,
                content="cross-process proof", consent_state="granted",
            ))
            session.add(ConsentScope(
                scope_id=scope_id, tenant_id=tenant, user_id=user,
                scope_name=scope_name, is_granted=True,
            ))

        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            assertion = (await session.execute(
                select(MemoryAssertion).where(
                    MemoryAssertion.assertion_id == assertion_id,
                )
            )).scalar_one()
            revision = assertion.updated_at
        if revision.tzinfo is None:
            revision = revision.replace(tzinfo=timezone.utc)
        origin = {
            "record_type": "memory_assertion",
            "record_id": str(assertion_id),
            "event_id": str(event_id),
            "record_updated_at": revision.astimezone(timezone.utc).isoformat(),
        }

        for _ in range(2):
            process = context.Process(
                target=_worker,
                args=(str(tenant), str(user), origin, ready, release, result),
            )
            process.start()
            workers.append(process)

        # Each process must independently authorize before the revoke commits.
        observed = [
            await asyncio.wait_for(
                asyncio.to_thread(ready.get, True, 25), timeout=30,
            )
            for _ in workers
        ]
        assert len({pid for pid, _ in observed}) == 2
        assert all(allowed is True for _, allowed in observed)

        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            scope = (await session.execute(
                select(ConsentScope).where(ConsentScope.scope_id == scope_id)
            )).scalar_one()
            scope.is_granted = False
            scope.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)

        # Commit is complete before either independent process reauthorizes.
        release.set()
        results = [
            await asyncio.wait_for(
                asyncio.to_thread(result.get, True, 25), timeout=30,
            )
            for _ in workers
        ]
        assert {item[0] for item in results} == {pid for pid, _ in observed}
        assert all(len(item) == 3 and item[1:] == (False, False)
                   for item in results), results
    finally:
        release.set()
        for process in workers:
            await asyncio.to_thread(process.join, 5)
            if process.is_alive():
                process.terminate()
                await asyncio.to_thread(process.join, 5)
            if process.is_alive():
                process.kill()
                await asyncio.to_thread(process.join, 5)
        ready.close()
        result.close()
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(delete(MemoryAssertion).where(
                MemoryAssertion.assertion_id == assertion_id,
            ))
            await session.execute(delete(MemoryEvent).where(
                MemoryEvent.event_id == event_id,
            ))
            await session.execute(delete(ConsentScope).where(
                ConsentScope.scope_id == scope_id,
            ))
