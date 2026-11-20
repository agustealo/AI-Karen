"""KCR-04A: observed, isolated PostgreSQL durable-recall execution proof.

Runs only with an explicitly enabled disposable PostgreSQL test database.
Exercises real PostgresRecallRetriever SQL, NeuroRecall candidate selection,
live scope/consent/validity, and an EXPLAIN (ANALYZE, BUFFERS) of the
same SQLAlchemy statement that the production retriever executes.

This does NOT prove the full MemoryRuntimeManager/Redis/graph composition,
memory_items pgvector/FTS integration, user-facing answer quality, or RLS
against a least-privilege DB role.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.dialects import postgresql

from ai_karen_engine.core.memory.retrieval.neuro_recall import (
    NeuroRecall,
    RecallRequest,
)
from ai_karen_engine.core.memory.types import MemoryQuery
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    ConsentScope,
    MemoryAssertion,
    MemoryEvent,
)
from ai_karen_engine.platform.memory.postgres.recall_retriever import (
    PostgresRecallRetriever,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1",
        reason="requires explicit disposable PostgreSQL test environment",
    ),
]

_TOKEN = "orchidcanary"


async def test_live_canonical_assertion_recall_query_and_neurorecall_selection() -> None:
    tenant, other_tenant = uuid.uuid4(), uuid.uuid4()
    user, other_user = uuid.uuid4(), uuid.uuid4()
    scope_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    event_ids: dict[str, uuid.UUID] = {}
    assertion_ids: dict[str, uuid.UUID] = {}
    explanation: dict = {}
    executed_sql: list[str] = []
    event_cases = (
        ("public", tenant, user, "memory.write", -2, None),
        ("private", tenant, user, "kcr04a.private", -2, None),
        ("other_user", tenant, other_user, "memory.write", -2, None),
        ("other_tenant", other_tenant, user, "memory.write", -2, None),
        ("expired", tenant, user, "memory.write", -5, -1),
        ("future", tenant, user, "memory.write", 2, None),
    )

    async def retrieve() -> list:
        return await PostgresRecallRetriever().recall(
            MemoryQuery(
                tenant_id=str(tenant),
                user_id=str(user),
                text=_TOKEN,
                top_k=20,
            )
        )

    def observed_ids(rows: list) -> set[str]:
        for row in rows:
            assert row.metadata is not None
            assert row.metadata.tenant_id == str(tenant)
            assert row.metadata.user_id == str(user)
            assert row.metadata.custom["provenance"]["record_type"] == "memory_assertion"
            assert row.metadata.custom["provenance"]["source_type"] == "chat"
            assert row.metadata.custom["provenance"]["source_ref"].startswith("kcr04a-test-message-")
            assert row.metadata.custom["provenance"]["event_id"] == (
                row.metadata.custom["event_id"]
            )
        return {row.metadata.custom["event_id"] for row in rows}

    try:
        for case, t_id, u_id, scope, start_offset, end_offset in event_cases:
            e_id, a_id = uuid.uuid4(), uuid.uuid4()
            event_ids[case], assertion_ids[case] = e_id, a_id
            start = now + timedelta(days=start_offset)
            end = now + timedelta(days=end_offset) if end_offset is not None else None
            async with async_transaction_scope(tenant_id=str(t_id)) as session:
                session.add(
                    MemoryEvent(
                        event_id=e_id,
                        tenant_id=t_id,
                        user_id=u_id,
                        source_type="chat",
                        source_ref=f"kcr04a-test-message-{case}",
                        payload_hash=uuid.uuid4().hex,
                        event_type="memory_persisted",
                        consent_state="granted",
                        valid_from=start,
                        valid_to=end,
                        payload={
                            "content": f"{_TOKEN} {case} research fixture",
                            "vault": {"consent_scope": scope},
                        },
                    )
                )
                await session.flush()
                session.add(
                    MemoryAssertion(
                        assertion_id=a_id,
                        event_id=e_id,
                        tenant_id=t_id,
                        user_id=u_id,
                        content=f"{_TOKEN} {case} research fixture",
                        confidence=0.92,
                        consent_state="granted",
                        valid_from=start,
                        valid_to=end,
                    )
                )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(
                ConsentScope(
                    scope_id=scope_id,
                    tenant_id=tenant,
                    user_id=user,
                    scope_name="kcr04a.private",
                    is_granted=True,
                )
            )

        before = await retrieve()
        assert observed_ids(before) == {
            str(event_ids["public"]),
            str(event_ids["private"]),
        }

        @asynccontextmanager
        async def instrumented_session():
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                class ObservedSession:
                    async def execute(self, statement):
                        compiled = str(
                            statement.compile(
                                dialect=postgresql.dialect(),
                                compile_kwargs={"literal_binds": True},
                            )
                        )
                        executed_sql.append(compiled)
                        plan_result = await session.execute(
                            text(
                                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
                                + compiled
                            )
                        )
                        plan_value = plan_result.scalar_one()
                        plan = (
                            json.loads(plan_value)
                            if isinstance(plan_value, str)
                            else plan_value
                        )
                        assert isinstance(plan, list) and plan[0]["Plan"]
                        explanation["top_node"] = plan[0]["Plan"]["Node Type"]
                        explanation["planning_ms"] = float(
                            plan[0].get("Planning Time", 0.0)
                        )
                        explanation["execution_ms"] = float(
                            plan[0].get("Execution Time", 0.0)
                        )
                        return await session.execute(statement)

                yield ObservedSession()

        observed = await PostgresRecallRetriever(
            session_factory=instrumented_session
        ).recall(
            MemoryQuery(
                tenant_id=str(tenant),
                user_id=str(user),
                text=_TOKEN,
                top_k=20,
            )
        )
        assert observed_ids(observed) == observed_ids(before)
        assert len(executed_sql) == 1
        sql = executed_sql[0].lower()
        assert "memory_assertion" in sql and "memory_event" in sql
        assert "consent_scope" in sql and "valid_to" in sql
        assert "memory_items" not in sql
        assert "to_tsvector" not in sql and "ts_rank" not in sql
        assert "<=>" not in sql and "vector_cosine" not in sql

        began = time.perf_counter()
        neuro = await NeuroRecall(retriever=PostgresRecallRetriever()).recall(
            RecallRequest(
                query=_TOKEN,
                tenant_id=str(tenant),
                user_id=str(user),
                top_k=20,
                latency_budget_ms=3000,
            )
        )
        neuro_observed_ms = (time.perf_counter() - began) * 1000
        assert not neuro.degraded, neuro.degradation_reason
        assert neuro.source_health[0]["status"] == "success"
        assert {str(row.metadata.custom["event_id"]) for row in neuro.memories} == {
            str(event_ids["public"]),
            str(event_ids["private"]),
        }
        assert all(
            item["provenance"]["event_id"]
            in {str(event_ids["public"]), str(event_ids["private"])}
            for item in neuro.provenance
        )

        # A later scope revocation suppresses private evidence immediately,
        # even though its historical event and assertion stay granted.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            grant = (
                await session.execute(
                    select(ConsentScope).where(ConsentScope.scope_id == scope_id)
                )
            ).scalar_one()
            grant.is_granted = False
            grant.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        assert observed_ids(await retrieve()) == {str(event_ids["public"])}
        revoked = await NeuroRecall(retriever=PostgresRecallRetriever()).recall(
            RecallRequest(
                query=_TOKEN,
                tenant_id=str(tenant),
                user_id=str(user),
                top_k=20,
                latency_budget_ms=3000,
            )
        )
        assert {str(row.metadata.custom["event_id"]) for row in revoked.memories} == {
            str(event_ids["public"])
        }
        assert not revoked.degraded

        for t_id, u_id in ((other_tenant, user), (tenant, other_user)):
            rows = await PostgresRecallRetriever().recall(
                MemoryQuery(
                    tenant_id=str(t_id),
                    user_id=str(u_id),
                    text=_TOKEN,
                    top_k=20,
                )
            )
            expected = (
                event_ids["other_tenant"]
                if t_id == other_tenant
                else event_ids["other_user"]
            )
            assert {row.metadata.custom["event_id"] for row in rows} == {
                str(expected)
            }

        # The existing disposable CI harness creates the canonical ledger
        # only, so record real availability separately from deployed use.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            capabilities = (
                await session.execute(
                    text(
                        "SELECT name, installed_version IS NOT NULL AS installed "
                        "FROM pg_available_extensions "
                        "WHERE name IN ('vector', 'pg_trgm') ORDER BY name"
                    )
                )
            ).all()
            memory_items = (
                await session.execute(
                    text("SELECT to_regclass('public.memory_items') IS NOT NULL")
                )
            ).scalar_one()
            indexes = (
                await session.execute(
                    text(
                        "SELECT tablename, indexname "
                        "FROM pg_indexes WHERE schemaname = 'public' "
                        "AND tablename IN ('memory_items', 'memory_assertion') "
                        "ORDER BY tablename, indexname"
                    )
                )
            ).all()

        report = {
            "case": "KCR-04A",
            "environment": "isolated_postgresql_disposable",
            "canonical_retrieval_table": "memory_assertion",
            "real_query_explain_node": explanation["top_node"],
            "explain_planning_ms": round(explanation["planning_ms"], 4),
            "explain_execution_ms": round(explanation["execution_ms"], 4),
            "neurorecall_single_observation_ms": round(neuro_observed_ms, 4),
            "available_extensions": {
                name: bool(installed) for name, installed in capabilities
            },
            "memory_items_table_present": bool(memory_items),
            "memory_index_names": [
                f"{table}.{name}" for table, name in indexes
            ],
            "canonical_query_has_vector_ranking": False,
            "canonical_query_has_postgres_fts": False,
            "scoped_consent_validity_and_neurorecall_proof": "passed",
            "full_runtime_embedding_graph_fts_benchmark": "not_tested",
            "measurements_are_p50_p95_or_p99": False,
        }
        destination = os.getenv("KCR04A_REPORT_PATH")
        if destination:
            Path(destination).write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    finally:
        # All source and derived fixture rows are deleted, never real data.
        for t_id, _user in ((tenant, user), (other_tenant, user)):
            keys = [
                event_id
                for case, event_id in event_ids.items()
                if (case == "other_tenant") == (t_id == other_tenant)
            ]
            if not keys:
                continue
            async with async_transaction_scope(tenant_id=str(t_id)) as session:
                await session.execute(
                    delete(MemoryAssertion).where(MemoryAssertion.event_id.in_(keys))
                )
                await session.execute(
                    delete(MemoryEvent).where(MemoryEvent.event_id.in_(keys))
                )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(
                delete(ConsentScope).where(ConsentScope.scope_id == scope_id)
            )
