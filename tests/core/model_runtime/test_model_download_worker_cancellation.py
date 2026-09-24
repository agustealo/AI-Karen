from __future__ import annotations

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
