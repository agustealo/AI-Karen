"""Stage telemetry must not expose private backend exception messages."""

from importlib import import_module
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_projection_stage_failure_logs_only_exception_type(monkeypatch):
    module = import_module(
        "ai_karen_engine.core.runtime.resilience.safe_stage_runner"
    )
    diagnostics = []
    log_lines = []
    failure_count = []

    class _Breaker:
        def allow_request(self):
            return True

        def record_failure(self):
            failure_count.append("failed")

        def record_success(self):
            raise AssertionError("A failing stage must not be marked successful")

    runner = module.SafeStageRunner()
    runner.flags = SimpleNamespace(is_enabled=lambda *args, **kwargs: True)
    runner.breakers = SimpleNamespace(get_breaker=lambda name: _Breaker())
    runner.policies = SimpleNamespace(
        get_policy=lambda name: SimpleNamespace(max_retries=0, timeout_seconds=1)
    )
    runner.fallbacks = SimpleNamespace(
        get_fallback=lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        module,
        "_emit_resilience_event",
        lambda event_name, **data: diagnostics.append((event_name, data)),
    )
    monkeypatch.setattr(
        module,
        "logger",
        SimpleNamespace(error=lambda msg: log_lines.append(msg)),
    )

    async def unavailable_projection():
        raise RuntimeError("database_password=never-expose-this")

    result = await runner.run_stage(
        "memory_graph_projection",
        "graph_relationships_enabled",
        unavailable_projection,
        tenant_id="tenant-1",
        user_id="user-1",
    )

    assert result is None
    assert len(failure_count) == 1
    assert any(
        details.get("error") == "RuntimeError"
        for _event, details in diagnostics
    )
    assert any(
        details.get("last_error") == "RuntimeError"
        for _event, details in diagnostics
    )
    assert "RuntimeError" in " ".join(log_lines)
    assert "never-expose-this" not in str(diagnostics)
    assert "never-expose-this" not in str(log_lines)
