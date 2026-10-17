"""Projection receipts distinguish policy-skipped optional workers from failures."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.memory.projections.manager import ProjectionManager


class _Worker:
    def __init__(self, outcome: bool):
        self.outcome = outcome
        self.calls = 0

    async def project(self, event_data, assertion_data=None):
        self.calls += 1
        return self.outcome


class _StageRunner:
    def __init__(self, *, graph_enabled: bool):
        self.calls = []
        self.flags = SimpleNamespace(
            is_enabled=lambda name, tenant, user: (
                graph_enabled if name == "graph_relationships_enabled" else True
            )
        )

    async def run_stage(self, *, stage_name, flag_name, func, **kwargs):
        self.calls.append((stage_name, flag_name))
        return await func(kwargs["event_data"], kwargs["assertion_data"])


def _event():
    return {"event_id": "evt-1", "tenant_id": "tenant-1", "user_id": "user-1"}


@pytest.mark.asyncio
async def test_disabled_graph_projection_is_skipped_not_reported_failed():
    hot = _Worker(True)
    graph = _Worker(False)
    manager = ProjectionManager({"stm": hot, "memory_graph": graph})
    runner = _StageRunner(graph_enabled=False)
    manager.safe_runner = runner

    results = await manager.project_event(_event())

    assert results == {"stm": True}
    assert hot.calls == 1
    assert graph.calls == 0
    assert runner.calls == [("stm_projection", "memory_learning_enabled")]


@pytest.mark.asyncio
async def test_enabled_graph_projection_failure_remains_visible():
    hot = _Worker(True)
    graph = _Worker(False)
    manager = ProjectionManager({"stm": hot, "memory_graph": graph})
    runner = _StageRunner(graph_enabled=True)
    manager.safe_runner = runner

    results = await manager.project_event(_event())

    assert results == {"stm": True, "memory_graph": False}
    assert hot.calls == 1
    assert graph.calls == 1
    assert len(runner.calls) == 2


@pytest.mark.asyncio
async def test_policy_disabled_workers_do_not_trigger_fallback_execution():
    worker = _Worker(False)
    manager = ProjectionManager({"memory_graph": worker})
    runner = _StageRunner(graph_enabled=False)
    manager.safe_runner = runner

    assert await manager.project_event(_event()) == {}
    assert worker.calls == 0
    assert runner.calls == []
