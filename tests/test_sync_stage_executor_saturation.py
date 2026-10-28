"""Concurrent admission proof for the bounded synchronous stage runner."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from test_bounded_sync_stage import _runner


@pytest.mark.asyncio
async def test_simultaneous_requests_do_not_exceed_worker_budget(monkeypatch):
    monkeypatch.setenv("MAX_WORKER_THREADS", "2")
    runner = _runner(timeout=0.15)
    release = threading.Event()
    started = threading.Event()
    lock = threading.Lock()
    active = 0
    peak = 0
    entered = 0

    def blocking():
        nonlocal active, peak, entered
        with lock:
            active += 1
            entered += 1
            peak = max(peak, active)
            if entered == 2:
                started.set()
        try:
            release.wait(timeout=2)
        finally:
            with lock:
                active -= 1

    try:
        tasks = [asyncio.create_task(runner.run_stage("spacy", "spacy", blocking)) for _ in range(24)]
        assert await asyncio.to_thread(started.wait, 1)
        results = await asyncio.gather(*tasks)
        assert results == ["degraded"] * 24
        assert entered == 2
        assert peak == 2
    finally:
        release.set()
    await asyncio.sleep(0.05)
    assert await runner.run_stage("spacy", "spacy", lambda: "recovered") == "recovered"


@pytest.mark.asyncio
async def test_cancelled_queued_executor_work_releases_capacity(monkeypatch):
    """A queued future cancelled before execution must not leak a permit."""
    monkeypatch.setenv("MAX_WORKER_THREADS", "1")
    runner = _runner(timeout=0.03)
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    occupying = threading.Event()
    release = threading.Event()
    def occupy():
        occupying.set()
        release.wait(timeout=2)
    loop.set_default_executor(executor)
    try:
        blocker = loop.run_in_executor(None, occupy)
        assert await asyncio.to_thread(occupying.wait, 1)
        assert await runner.run_stage("spacy", "spacy", lambda: "queued") == "degraded"
        release.set()
        await blocker
        await asyncio.sleep(0.05)
        assert await runner.run_stage("spacy", "spacy", lambda: "recovered") == "recovered"
    finally:
        release.set()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=4))
        executor.shutdown(wait=True)
