from __future__ import annotations

import asyncio
from typing import Any, Optional

import pytest

from ai_karen_engine.config.model_download import ModelDownloadWorkerSettings
from ai_karen_engine.core.model_runtime.model_download_worker import ModelDownloadWorker


class CancellationService:
    def __init__(self, status: Optional[str]) -> None:
        self.status = status
        self.release_calls: list[tuple[str, str]] = []

    async def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        if self.status is None:
            return None
        return {"job_id": job_id, "status": self.status}

    async def release_claim_for_shutdown(self, job_id: str, lease_token: str) -> None:
        self.release_calls.append((job_id, lease_token))


def _settings() -> ModelDownloadWorkerSettings:
    return ModelDownloadWorkerSettings(
        lease_seconds=30,
        heartbeat_seconds=5,
        poll_interval_seconds=0.01,
        max_attempts=3,
        retry_base_seconds=1,
        shutdown_grace_seconds=0,
    ).validate()


@pytest.mark.asyncio
async def test_cancelled_promotion_keeps_lease_fenced_until_expiry() -> None:
    service = CancellationService("promoting")
    worker = ModelDownloadWorker(service, _settings())

    await worker._release_cancelled_claim("mdl-promoting", "lease-promoting")

    assert service.release_calls == []


@pytest.mark.asyncio
async def test_cancelled_running_download_releases_claim_for_retry() -> None:
    service = CancellationService("running")
    worker = ModelDownloadWorker(service, _settings())

    await worker._release_cancelled_claim("mdl-running", "lease-running")

    assert service.release_calls == [("mdl-running", "lease-running")]


@pytest.mark.asyncio
async def test_unknown_cancel_state_fails_closed_without_releasing_claim() -> None:
    class FailingService(CancellationService):
        async def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
            del job_id
            raise RuntimeError("database unavailable")

    service = FailingService("running")
    worker = ModelDownloadWorker(service, _settings())

    await worker._release_cancelled_claim("mdl-unknown", "lease-unknown")

    assert service.release_calls == []


@pytest.mark.asyncio
async def test_graceful_shutdown_keeps_active_execution_lease_renewed() -> None:
    class GracefulShutdownService(CancellationService):
        def __init__(self) -> None:
            super().__init__("running")
            self.claimed = False
            self.execution_started = asyncio.Event()
            self.allow_finish = asyncio.Event()
            self.second_heartbeat = asyncio.Event()
            self.heartbeat_count = 0

        async def get_global_concurrency_limit(self) -> int:
            return 1

        async def claim_next_job(self, worker_id: str) -> Optional[dict[str, Any]]:
            del worker_id
            if self.claimed:
                return None
            self.claimed = True
            return {
                "job_id": "mdl-graceful",
                "lease_token": "lease-graceful",
            }

        async def execute_claimed_job(self, claim: dict[str, Any]) -> None:
            assert claim["job_id"] == "mdl-graceful"
            self.execution_started.set()
            await self.allow_finish.wait()

        async def heartbeat_claim(self, job_id: str, lease_token: str) -> bool:
            assert job_id == "mdl-graceful"
            assert lease_token == "lease-graceful"
            self.heartbeat_count += 1
            if self.heartbeat_count >= 2:
                self.second_heartbeat.set()
            return True

        async def fail_claim(self, job_id: str, lease_token: str, exc: Exception) -> None:
            raise AssertionError(
                f"graceful execution unexpectedly failed: {job_id} {lease_token} {exc}"
            )

    settings = ModelDownloadWorkerSettings(
        lease_seconds=2,
        heartbeat_seconds=0.01,
        poll_interval_seconds=0.005,
        max_attempts=3,
        retry_base_seconds=1,
        shutdown_grace_seconds=0.5,
    ).validate()
    service = GracefulShutdownService()
    worker = ModelDownloadWorker(service, settings)

    await worker.start()
    await asyncio.wait_for(service.execution_started.wait(), timeout=0.2)

    stop_task = asyncio.create_task(worker.stop())
    await asyncio.wait_for(service.second_heartbeat.wait(), timeout=0.2)

    assert not stop_task.done()
    assert service.heartbeat_count >= 2

    service.allow_finish.set()
    await asyncio.wait_for(stop_task, timeout=0.2)

    assert service.release_calls == []
