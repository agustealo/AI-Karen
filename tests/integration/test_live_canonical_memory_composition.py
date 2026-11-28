"""KIS-GRAPH-01C2R-I: real Redis, graph and PostgreSQL memory composition.

Reuse MemoryRuntimeManager/NeuroRecall with actual backend connections.
The PostgreSQL event ledger remains the consent and identity authority.
No provider, network streaming, or durable transcript claim is made.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text

from ai_karen_engine.core.memory.graph.service import get_leangraph_service
from ai_karen_engine.core.memory.memory_runtime_manager import MemoryRuntimeManager
from ai_karen_engine.core.memory.projections.hot_state_worker import HotStateWorker
from ai_karen_engine.core.memory.stm import STMScope, STMSlot
from ai_karen_engine.persistence.postgres.engine import get_postgres_engine
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    MemoryAssertion, MemoryEntity, MemoryEvent, MemoryRelation,
)
from ai_karen_engine.platform.memory.redis.redis_connection_manager import RedisConnectionManager
from ai_karen_engine.platform.memory.redis.stm_adapter import RedisSTMAdapter


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.timeout(180)
@pytest.mark.skipif(
    os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1"
    or os.getenv("KAREN_TEST_DISPOSABLE_DATABASE") != "1"
    or os.getenv("KAREN_TEST_REAL_REDIS_GRAPH") != "1",
    reason="requires explicit disposable PostgreSQL and real Redis/graph services",
)
async def test_live_canonical_redis_graph_postgres_memory_composition() -> None:
    """Prove real multi-source selection and revalidation on consent withdrawal."""
    samples = int(os.getenv("KAREN_MEMORY_COMPOSITION_SAMPLES", "8"))
    if not 2 <= samples <= 32:
        raise ValueError("KAREN_MEMORY_COMPOSITION_SAMPLES must be between 2 and 32")
    report_path = Path(os.getenv(
        "KAREN_MEMORY_COMPOSITION_REPORT", "memory-composition-acceptance.json",
    ))
    if report_path.suffix != ".json":
        raise ValueError("Composition report must be JSON")
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        raise ValueError("REDIS_URL is required for an actual Redis service")

    tenant, user, foreign_tenant, foreign_user = (
        uuid4(), uuid4(), uuid4(), uuid4(),
    )
    event_id, assertion_id = uuid4(), uuid4()
    # Use a lowercase fixture token because canonical lexical recall currently
    # casefolds terms but uses a case-sensitive PostgreSQL contains predicate.
    cue = f"prism{uuid4().hex[:16]}"
    content = f"Project {cue} was authorized for session continuity"
    session_id = f"session-{uuid4().hex}"
    query = f"why did we link the relation with {cue}"
    scope = STMScope(tenant_id=str(tenant), user_id=str(user), session_id=session_id)
    slots = (STMSlot.RECENT_CONTEXT, STMSlot.ACTIVE_GOAL)

    engine = get_postgres_engine()
    checked_out_before = engine.async_engine.pool.checkedout()
    redis = RedisConnectionManager(
        redis_url=redis_url, prefix=f"karen-ci-composition-{uuid4().hex}",
    )
    stm = None
    graph = get_leangraph_service()
    seeded = False
    started = time.perf_counter()
    failure_type = None
    cleanup_errors: list[str] = []
    report = {
        "schema_version": 1,
        "test": "KIS-GRAPH-01C2R-I",
        "status": "incomplete",
        "real_services": {"postgres": False, "redis": False, "graph": False},
        "samples": samples,
        "limitations": [
            "No real model inference or authenticated HTTP/SSE delivery",
            "No durable chat transcript or atomic database-to-wire consent lease",
            "CI-host timings are smoke evidence, not a production latency SLO",
        ],
    }

    def stores(result: dict) -> set[str]:
        return {
            str(value.get("source_store"))
            for value in result["provenance"]
            if isinstance(value, dict)
        }

    try:
        assert engine.async_engine.dialect.name == "postgresql"
        report["real_services"]["postgres"] = True
        assert await redis.initialize(), "Actual Redis service is required"
        assert not redis.is_degraded(), "Redis fallback cannot certify this test"
        client = redis.client
        assert client is not None and await client.ping()
        stm = RedisSTMAdapter(redis_manager=redis)
        report["real_services"]["redis"] = True

        assert getattr(graph.adapter, "backend_name", None) == "postgres"
        assert getattr(graph.adapter, "durable", None) is True
        await graph.initialize()
        report["real_services"]["graph"] = True

        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(MemoryEvent(
                event_id=event_id, tenant_id=tenant, user_id=user,
                event_type="memory_persisted", source_type="conversation",
                payload_hash=uuid4().hex, consent_state="granted",
                payload={
                    "content": content,
                    "entities": [{"text": cue, "type": "project"}],
                    "vault": {"consent_scope": "memory.write"},
                },
            ))
            await session.flush()
            session.add(MemoryAssertion(
                assertion_id=assertion_id, event_id=event_id,
                tenant_id=tenant, user_id=user, content=content,
                consent_state="granted",
            ))
        seeded = True

        assert await graph.project_memory_event({
            "event_id": str(event_id), "tenant_id": str(tenant),
            "user_id": str(user),
            "payload": {"entities": [{"text": cue, "type": "project"}]},
        }) is True
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            entity_rows = (await session.execute(select(MemoryEntity).where(
                MemoryEntity.tenant_id == tenant,
                MemoryEntity.user_id == user,
                MemoryEntity.normalized_text == cue.casefold(),
            ))).scalars().all()
            edge_rows = (await session.execute(select(MemoryRelation).where(
                MemoryRelation.tenant_id == tenant,
                MemoryRelation.user_id == user,
                MemoryRelation.source_event_id == event_id,
            ))).scalars().all()
        assert len(entity_rows) == 1 and len(edge_rows) >= 1
        assert any(str(item["event_id"]) == str(event_id)
                   for item in await graph.get_entity_context(
                       tenant_id=str(tenant), user_id=str(user), entity_text=cue,
                   ))

        assert await stm.put_slot(
            scope=scope, slot=STMSlot.RECENT_CONTEXT,
            value={"latest": {
                "content": content, "event_id": str(event_id),
                "source_type": "conversation", "source_ref": None,
            }},
        )
        assert await stm.put_slot(
            scope=scope, slot=STMSlot.ACTIVE_GOAL,
            value={"goal": f"Complete {cue} project"},
        )
        for slot in slots:
            assert await stm.get_slot(scope=scope, slot=slot)
        assert not stm.degraded()

        manager = MemoryRuntimeManager(
            stm=stm, formation_service=MagicMock(), control_service=MagicMock(),
        )

        async def recall(tenant_id: str, user_id: str, session: str):
            return await manager.recall_context(
                tenant_id=tenant_id, user_id=user_id, session_id=session,
                query=query, top_k=10, latency_budget_ms=5000,
            )

        warm = await recall(str(tenant), str(user), session_id)
        assert warm["status"] == "success" and not warm["degraded"]
        health = warm["retrieval_health"]
        assert health["retriever_count"] == 5
        assert health["failed_retriever_count"] == 0
        assert health["timed_out_retriever_count"] == 0
        assert all(source["status"] == "success" for source in health["source_health"])
        router = [
            source for source in health["source_health"]
            if source["retriever"] == "HybridRetrievalRouter"
        ]
        assert len(router) == 1 and router[0]["candidate_count"] >= 3
        assert {"stm", "postgres_graph", "postgres"}.issubset(stores(warm))
        assert all(row["metadata"]["tenant_id"] == str(tenant)
                   and row["metadata"]["user_id"] == str(user)
                   for row in warm["results"])

        observed_ms = []
        for _ in range(samples):
            result = await recall(str(tenant), str(user), session_id)
            assert result["status"] == "success" and not result["degraded"]
            assert {"stm", "postgres_graph", "postgres"}.issubset(stores(result))
            observed_ms.append(round(float(result["latency_ms"]), 3))
        ordered = sorted(observed_ms)
        report["composed_recall"] = {
            "completed": len(ordered),
            "retrievers": health["retriever_count"],
            "selected_stores": sorted(stores(warm)),
            "p50_ms": ordered[(len(ordered) - 1) // 2],
            "p95_ms": ordered[max(0, (len(ordered) * 95 + 99) // 100 - 1)],
        }

        foreign_user_result = await recall(str(tenant), str(foreign_user), session_id)
        foreign_tenant_result = await recall(str(foreign_tenant), str(user), session_id)
        different_session_result = await recall(str(tenant), str(user), "different-session")
        assert not foreign_user_result["results"]
        assert not foreign_tenant_result["results"]
        assert "stm" not in stores(different_session_result)
        assert "postgres_graph" in stores(different_session_result)
        report["identity_isolation"] = "passed"
        report["session_isolation"] = "passed"

        # A stale Redis slot is not revocation authority. Both event-derived
        # STM and graph candidates must disappear after PostgreSQL withdrawal.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            event = (await session.execute(select(MemoryEvent).where(
                MemoryEvent.event_id == event_id,
            ))).scalar_one()
            event.consent_state = "revoked"
            event.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        assert await stm.get_slot(scope=scope, slot=STMSlot.RECENT_CONTEXT)
        after = await recall(str(tenant), str(user), session_id)
        assert after["status"] == "success" and not after["degraded"]
        assert "postgres_graph" not in stores(after)
        assert all(row["content"] != content for row in after["results"])
        assert not {str(event_id), str(assertion_id)}.intersection(
            str(row["id"]) for row in after["results"]
        )
        assert not await graph.get_entity_context(
            tenant_id=str(tenant), user_id=str(user), entity_text=cue,
        )
        assert "stm" in stores(after)  # independent session-only goal survives
        report["revocation"] = "event_derived_redis_and_graph_denied"

        # A delayed producer may replay the already committed event after the
        # consent transaction has committed. Exercise the actual projection
        # worker rather than only leaving an old Redis value in place.
        assert await stm.delete_slot(scope=scope, slot=STMSlot.RECENT_CONTEXT)
        assert await stm.get_slot(scope=scope, slot=STMSlot.RECENT_CONTEXT) is None
        worker = HotStateWorker(stm)
        published = await worker.project(
            {
                "event_id": str(event_id), "tenant_id": str(tenant),
                "user_id": str(user), "session_id": session_id,
                "source_type": "conversation", "source_ref": None,
                "payload": {"content": content},
            },
            {
                "assertion_id": str(assertion_id), "event_id": str(event_id),
                "text": content,
            },
        )
        # A future write-side fence may deny publication outright. If the
        # cache accepts a stale projection, canonical recall still must deny it.
        stale = await stm.get_slot(scope=scope, slot=STMSlot.RECENT_CONTEXT)
        if published:
            assert stale is not None
            assert stale["latest"]["event_id"] == str(event_id)
        else:
            assert stale is None
        replay = await recall(str(tenant), str(user), session_id)
        assert replay["status"] == "success" and not replay["degraded"]
        assert all(row["content"] != content for row in replay["results"])
        assert not {str(event_id), str(assertion_id)}.intersection(
            str(row["id"]) for row in replay["results"]
        )
        assert "postgres_graph" not in stores(replay)
        assert "stm" in stores(replay)
        report["delayed_stm_publication"] = (
            "stale_cache_recall_denied" if published else "publication_denied"
        )
        # The existing cleanup expects both scoped slots to be present.
        # Only delete an extant recent-context slot at cleanup if the
        # future publisher has already denied the delayed write.
        if stale is None:
            slots = (STMSlot.ACTIVE_GOAL,)

        async with engine.async_session_factory() as session:
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
        assert engine.async_engine.pool.checkedout() == checked_out_before
        report["status"] = "complete"
    except BaseException as exc:
        failure_type = type(exc).__name__
        raise
    finally:
        if stm is not None:
            for slot in slots:
                try:
                    if not await stm.delete_slot(scope=scope, slot=slot):
                        cleanup_errors.append("RedisSlotDeleteFailed")
                except BaseException as exc:
                    cleanup_errors.append(type(exc).__name__)
        if seeded:
            try:
                async with async_transaction_scope(tenant_id=str(tenant)) as session:
                    await session.execute(delete(MemoryRelation).where(
                        MemoryRelation.tenant_id == tenant,
                        MemoryRelation.source_event_id == event_id,
                    ))
                    await session.execute(delete(MemoryEntity).where(
                        MemoryEntity.tenant_id == tenant,
                        MemoryEntity.user_id == user,
                        MemoryEntity.normalized_text == cue.casefold(),
                    ))
                    await session.execute(delete(MemoryAssertion).where(
                        MemoryAssertion.assertion_id == assertion_id,
                    ))
                    await session.execute(delete(MemoryEvent).where(
                        MemoryEvent.event_id == event_id,
                    ))
            except BaseException as exc:
                cleanup_errors.append(type(exc).__name__)
        try:
            await redis.close()
        except BaseException as exc:
            cleanup_errors.append(type(exc).__name__)
        checked_out_after = engine.async_engine.pool.checkedout()
        report["checked_out_after_cleanup"] = checked_out_after
        report["failure_type"] = failure_type
        report["cleanup_errors"] = cleanup_errors
        report["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        if (report["status"] != "complete" or failure_type is not None
                or cleanup_errors or checked_out_after != checked_out_before):
            report["status"] = "incomplete"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        if failure_type is None:
            assert not cleanup_errors, "Composition fixture cleanup failed"
            assert checked_out_after == checked_out_before
