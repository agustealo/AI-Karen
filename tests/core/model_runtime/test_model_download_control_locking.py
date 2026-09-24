from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from ai_karen_engine.core.model_runtime.model_download_control_service import (
    ModelDownloadControlService,
)


def _service(tmp_path) -> ModelDownloadControlService:
    return ModelDownloadControlService(
        {
            "models_root": str(tmp_path / "models"),
            "runtime_registry_root": str(tmp_path / "runtime-registry"),
            "registry_path": str(tmp_path / "models" / "llm_registry.json"),
            "max_concurrent_downloads": 1,
        }
    )


def _read_state(service: ModelDownloadControlService) -> dict[str, Any]:
    return json.loads(service.state_path.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_policy_update_persists_without_reentrant_lock_deadlock(tmp_path):
    service = _service(tmp_path)

    policy = await asyncio.wait_for(
        service.update_policy(
            {
                "block_new_downloads": True,
                "max_concurrent_downloads": 1,
            }
        ),
        timeout=1.0,
    )

    assert policy["block_new_downloads"] is True
    assert policy["max_concurrent_downloads"] == 1

    persisted = _read_state(service)
    assert persisted["policy"]["block_new_downloads"] is True
    assert persisted["policy"]["max_concurrent_downloads"] == 1

    with pytest.raises(
        RuntimeError,
        match="state persistence requires the mutation lock",
    ):
        await service._persist_state()


@pytest.mark.asyncio
async def test_job_control_transitions_persist_without_reentrant_lock_deadlock(
    tmp_path,
    monkeypatch,
):
    service = _service(tmp_path)
    executor_entered = asyncio.Event()
    release_executor = asyncio.Event()

    async def blocked_executor(job_id: str) -> None:
        del job_id
        executor_entered.set()
        await release_executor.wait()

    monkeypatch.setattr(service, "_run_download_job", blocked_executor)

    job = await asyncio.wait_for(
        service.start_download(
            {
                "model_id": "test-owner/test-model",
                "channel_id": "core_runtime_transformers",
            },
            {"user_id": "test-user"},
        ),
        timeout=1.0,
    )
    job_id = job["job_id"]
    await asyncio.wait_for(executor_entered.wait(), timeout=1.0)

    persisted = _read_state(service)
    persisted_job = next(item for item in persisted["jobs"] if item["job_id"] == job_id)
    assert persisted_job["status"] == "queued"

    paused = await asyncio.wait_for(service.pause_job(job_id), timeout=1.0)
    assert paused["status"] == "paused"
    persisted = _read_state(service)
    persisted_job = next(item for item in persisted["jobs"] if item["job_id"] == job_id)
    assert persisted_job["status"] == "paused"

    resumed = await asyncio.wait_for(service.resume_job(job_id), timeout=1.0)
    assert resumed["status"] == "queued"
    persisted = _read_state(service)
    persisted_job = next(item for item in persisted["jobs"] if item["job_id"] == job_id)
    assert persisted_job["status"] == "queued"

    cancelled = await asyncio.wait_for(service.cancel_job(job_id), timeout=1.0)
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancel_requested"] is True
    persisted = _read_state(service)
    persisted_job = next(item for item in persisted["jobs"] if item["job_id"] == job_id)
    assert persisted_job["status"] == "cancelled"
    assert persisted_job["cancel_requested"] is True

    release_executor.set()
    await asyncio.wait_for(service._tasks[job_id], timeout=1.0)
