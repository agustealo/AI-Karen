"""KCR-04F: real PostgreSQL half-open recall and consent-boundary proof.

Use committed event/assertion rows and canonical PostgresRecallRetriever SQL.
This proves scoped selection, not FORCE RLS under a least-privilege DB role.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from ai_karen_engine.core.memory.types import MemoryQuery
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres import recall_retriever
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    ConsentScope,
    MemoryAssertion,
    MemoryEvent,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1",
        reason="requires disposable canonical PostgreSQL memory ledger",
    ),
]


async def test_source_and_assertion_use_one_exclusive_utc_end_and_current_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, foreign_tenant_id = uuid.uuid4(), uuid.uuid4()
    user_id, foreign_user_id = uuid.uuid4(), uuid.uuid4()
    scope_id = uuid.uuid4()
    consent_scope = f"kcr04f.{uuid.uuid4().hex}"
    token = f"kcr04f{uuid.uuid4().hex}"
    boundary = datetime(2031, 7, 1, 12, tzinfo=timezone.utc)
    inserted: dict[uuid.UUID, list[uuid.UUID]] = {
        tenant_id: [],
        foreign_tenant_id: [],
    }

    # Offsets are microseconds relative to the same instant. None is open.
    # Denied records have higher confidence to test filtering before LIMIT.
    cases = (
        ("source_end", tenant_id, user_id, -1000000, 0, -1000000, None, "granted", "granted", "memory.write"),
        ("assertion_end", tenant_id, user_id, -1000000, None, -1000000, 0, "granted", "granted", "memory.write"),
        ("source_start", tenant_id, user_id, 0, None, -1000000, None, "granted", "granted", "memory.write"),
        ("assertion_start", tenant_id, user_id, -1000000, None, 0, None, "granted", "granted", "memory.write"),
        ("continuous", tenant_id, user_id, None, None, None, None, "granted", "granted", "memory.write"),
        ("source_future", tenant_id, user_id, 1000000, None, -1000000, None, "granted", "granted", "memory.write"),
        ("assertion_future", tenant_id, user_id, -1000000, None, 1000000, None, "granted", "granted", "memory.write"),
        ("source_denied", tenant_id, user_id, -1000000, None, -1000000, None, "revoked", "granted", "memory.write"),
        ("assertion_denied", tenant_id, user_id, -1000000, None, -1000000, None, "granted", "revoked", "memory.write"),
        ("scoped", tenant_id, user_id, -1000000, None, -1000000, None, "granted", "granted", consent_scope),
        ("foreign_user", tenant_id, foreign_user_id, -1000000, None, -1000000, None, "granted", "granted", "memory.write"),
        ("foreign_tenant", foreign_tenant_id, user_id, -1000000, None, -1000000, None, "granted", "granted", "memory.write"),
    )

    def instant(offset: int | None) -> datetime | None:
        return (
            None
            if offset is None
            else (boundary + timedelta(microseconds=offset)).replace(tzinfo=None)
        )

    class FrozenUTCClock:
        at: datetime = boundary
        observed: list[timezone | None] = []

        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            cls.observed.append(tz)
            assert tz is timezone.utc
            return cls.at

    async def recall(*, top_k: int = 50) -> set[str]:
        rows = await recall_retriever.PostgresRecallRetriever().recall(
            MemoryQuery(
                tenant_id=str(tenant_id),
                user_id=str(user_id),
                text=token,
                top_k=top_k,
            )
        )
        assert all(
            entry.metadata is not None
            and entry.metadata.tenant_id == str(tenant_id)
            and entry.metadata.user_id == str(user_id)
            and entry.metadata.custom["source_store"] == "postgres"
            and entry.metadata.custom["provenance"]["record_type"] == "memory_assertion"
            for entry in rows
        )
        return {entry.content.split()[-1] for entry in rows}

    try:
        for (
            name, row_tenant, row_user, event_from, event_to,
            assertion_from, assertion_to, event_consent, assertion_consent,
            source_scope,
        ) in cases:
            event_id = uuid.uuid4()
            inserted[row_tenant].append(event_id)
            async with async_transaction_scope(tenant_id=str(row_tenant)) as session:
                session.add(
                    MemoryEvent(
                        event_id=event_id,
                        tenant_id=row_tenant,
                        user_id=row_user,
                        source_type="kcr04f_integrated_recall",
                        payload_hash=uuid.uuid4().hex,
                        event_type="memory_persisted",
                        consent_state=event_consent,
                        valid_from=instant(event_from),
                        valid_to=instant(event_to),
                        payload={
                            "content": f"{token} {name}",
                            "vault": {"consent_scope": source_scope},
                        },
                    )
                )
                await session.flush()
                session.add(
                    MemoryAssertion(
                        assertion_id=uuid.uuid4(),
                        event_id=event_id,
                        tenant_id=row_tenant,
                        user_id=row_user,
                        content=f"{token} {name}",
                        confidence=1.0 if name.endswith("denied") else 0.8,
                        consent_state=assertion_consent,
                        valid_from=instant(assertion_from),
                        valid_to=instant(assertion_to),
                    )
                )

        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            session.add(
                ConsentScope(
                    scope_id=scope_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    scope_name=consent_scope,
                    is_granted=True,
                )
            )

        monkeypatch.setattr(recall_retriever, "datetime", FrozenUTCClock)
        before = {"source_end", "assertion_end", "continuous", "scoped"}
        exact = {"source_start", "assertion_start", "continuous", "scoped"}
        for delta, expected in (
            (timedelta(microseconds=-1), before),
            (timedelta(0), exact),
            (timedelta(microseconds=1), exact),
        ):
            FrozenUTCClock.at = boundary + delta
            FrozenUTCClock.observed.clear()
            assert await recall() == expected
            assert FrozenUTCClock.observed == [timezone.utc]

        # Current revocation overrides the historical grant on the source.
        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            stored_scope = (
                await session.execute(
                    select(ConsentScope).where(ConsentScope.scope_id == scope_id)
                )
            ).scalar_one()
            stored_scope.is_granted = False
            stored_scope.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)

        FrozenUTCClock.at = boundary
        assert await recall() == exact - {"scoped"}
        # Denied high-confidence evidence must not consume the top-ranked slot.
        top = await recall(top_k=1)
        assert len(top) == 1
        assert top.issubset(exact - {"scoped"})
    finally:
        for row_tenant, event_ids in inserted.items():
            if not event_ids:
                continue
            async with async_transaction_scope(tenant_id=str(row_tenant)) as session:
                await session.execute(
                    delete(MemoryAssertion).where(
                        MemoryAssertion.event_id.in_(event_ids)
                    )
                )
                await session.execute(
                    delete(MemoryEvent).where(MemoryEvent.event_id.in_(event_ids))
                )
        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            await session.execute(
                delete(ConsentScope).where(ConsentScope.scope_id == scope_id)
            )
