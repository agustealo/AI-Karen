"""Bounded synchronous stage execution protects executor capacity after timeouts."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.resilience.safe_stage_runner import (
    SafeStageRunner,
    _sync_stage_capacity,
)


def _runner(timeout=0.02):
    runner = SafeStageRunner()
    runner.flags = SimpleNamespace(is_enabled=lambda *args: True)
    runner.breakers = SimpleNamespace(get_breaker=lambda name: SimpleNamespace(
        allow_request=lambda: True, record_failure=lambda: None, record_success=lambda: None,
    ))
    runner.policies = SimpleNamespace(get_policy=lambda name: SimpleNamespace(
        timeout_seconds=timeout, max_retries=0,
    ))
    runner.fallbacks = SimpleNamespace(get_fallback=lambda *args, **kwargs: "degraded")
    return runner


def test_sync_capacity_validation(monkeypatch):
    monkeypatch.setenv("MAX_WORKER_THREADS", "2")
    assert _sync_stage_capacity() == 2
    for invalid in ("0", "-1", "129", "abc"):
        monkeypatch.setenv("MAX_WORKER_THREADS", invalid)
        with pytest.raises(ValueError):
            _sync_stage_capacity()


@pytest.mark.asyncio
async def test_timeout_holds_capacity_until_worker_finishes(monkeypatch):
    monkeypatch.setenv("MAX_WORKER_THREADS", "1")
    runner = _runner()
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def blocking():
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=2)
        return "finished"

    try:
        assert await runner.run_stage("spacy", "spacy", blocking) == "degraded"
        assert started.is_set()
        assert await runner.run_stage("spacy", "spacy", blocking) == "degraded"
        assert calls == 1
    finally:
        release.set()
    await asyncio.sleep(0.05)
    assert await runner.run_stage("spacy", "spacy", lambda: "recovered") == "recovered"
