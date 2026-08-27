import pytest

from ai_karen_engine.core.memory.graph.config import LeanGraphConfig
from ai_karen_engine.core.memory.graph.models import GraphEdge
from ai_karen_engine.core.memory.graph.service import LeanGraphService


@pytest.mark.asyncio
async def test_projection_creates_mentions_and_supersedes_edges(tmp_path):
    cfg = LeanGraphConfig(graph_db_path=str(tmp_path), graph_backend="in_memory")
    svc = LeanGraphService(cfg)
    ok = await svc.project_memory_event(
        {
            "event_id": "e1",
            "tenant_id": "t1",
            "user_id": "u1",
            "supersedes": "e0",
            "payload": {"entities": [{"text": "Detroit"}]},
        }
    )
    assert ok is True
    ctx = await svc.get_entity_context("t1", "u1", "Detroit")
    assert any(row["event_id"] == "e1" for row in ctx)


@pytest.mark.asyncio
async def test_in_memory_graph_honors_bounded_multi_hop_depth(tmp_path):
    cfg = LeanGraphConfig(graph_db_path=str(tmp_path), graph_backend="in_memory")
    svc = LeanGraphService(cfg)
    await svc.initialize()

    await svc.adapter.create_edge(GraphEdge("e1", "e2", "RELATED_TO", "t1", "u1"))
    await svc.adapter.create_edge(GraphEdge("e2", "e3", "RELATED_TO", "t1", "u1"))

    depth_one = await svc.get_related_context("t1", "u1", "e1", max_depth=1)
    depth_two = await svc.get_related_context("t1", "u1", "e1", max_depth=2)

    assert {row["event_id"] for row in depth_one} == {"e2"}
    assert {row["event_id"] for row in depth_two} == {"e2", "e3"}


@pytest.mark.asyncio
async def test_in_memory_graph_enforces_tenant_user_scope(tmp_path):
    cfg = LeanGraphConfig(graph_db_path=str(tmp_path), graph_backend="in_memory")
    svc = LeanGraphService(cfg)
    await svc.initialize()

    await svc.adapter.create_edge(GraphEdge("e1", "same", "RELATED_TO", "t1", "u1"))
    await svc.adapter.create_edge(GraphEdge("e1", "other-tenant", "RELATED_TO", "t2", "u1"))
    await svc.adapter.create_edge(GraphEdge("e1", "other-user", "RELATED_TO", "t1", "u2"))

    rows = await svc.get_related_context("t1", "u1", "e1", max_depth=1)
    assert {row["event_id"] for row in rows} == {"same"}


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_repeated_failures(tmp_path):
    cfg = LeanGraphConfig(graph_db_path=str(tmp_path), graph_backend="in_memory")
    svc = LeanGraphService(cfg)
    svc._failure_threshold = 1

    async def fail(*_args, **_kwargs):
        raise RuntimeError("boom")

    svc.adapter.upsert_entity = fail  # type: ignore[method-assign]
    ok = await svc.project_memory_event(
        {
            "event_id": "e1",
            "tenant_id": "t1",
            "user_id": "u1",
            "payload": {"entities": [{"text": "Detroit"}]},
        }
    )
    assert ok is False

    skipped = await svc.project_memory_event(
        {
            "event_id": "e2",
            "tenant_id": "t1",
            "user_id": "u1",
            "payload": {},
        }
    )
    assert skipped is False
