from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest

from ai_karen_engine.persistence.repositories.model_download_repository import (
    ModelDownloadRepository,
)


DATABASE_URL = os.environ.get("MODEL_DOWNLOAD_TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="MODEL_DOWNLOAD_TEST_DATABASE_URL is required for PostgreSQL lease proofs",
    ),
]


def _payload(job_id: str, model_id: str) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "model_id": model_id,
        "revision": None,
        "channel_id": "core_runtime_transformers",
        "storage_key": "transformers",
        "progress": 0.0,
        "message": "Queued for download",
        "error": None,
        "result": None,
        "requested_by": "integration-test",
        "trust_remote_code": False,
        "license_accepted": True,
        "include_patterns": None,
        "exclude_patterns": None,
        "pin": False,
        "force_redownload": False,
        "warnings": [],
        "detected_runtime": "vllm",
        "detected_modality": "text",
        "install_path": f"/tmp/{job_id}",
    }


@pytest.fixture(autouse=True)
def reset_download_authority() -> None:
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute("TRUNCATE TABLE public.model_download_jobs")
        connection.execute(
            """
            INSERT INTO public.model_download_runtime_settings (
                singleton, max_concurrent_downloads
            ) VALUES (true, 1)
            ON CONFLICT (singleton) DO UPDATE
            SET max_concurrent_downloads = EXCLUDED.max_concurrent_downloads
            """
        )


async def _queue_pair(repository: ModelDownloadRepository, prefix: str) -> tuple[str, str]:
    first = f"mdl-{prefix}-first"
    second = f"mdl-{prefix}-second"
    await repository.create_job(
        _payload(first, f"test-owner/{prefix}-first"),
        max_attempts=3,
    )
    await repository.create_job(
        _payload(second, f"test-owner/{prefix}-second"),
        max_attempts=3,
    )
    return first, second


async def test_running_pause_retains_lease_until_active_transfer_stops() -> None:
    repository = ModelDownloadRepository()
    first, _ = await _queue_pair(repository, "pause")

    claim = await repository.claim_next(
        worker_id="worker-a",
        lease_seconds=30,
        retry_base_seconds=0,
    )
    assert claim is not None and claim["job_id"] == first
    lease_token = str(claim["lease_token"])

    paused = await repository.pause_job(first)
    assert paused is not None
    assert paused["status"] == "pause_requested"
    assert paused["pause_requested"] is True
    assert str(paused["lease_token"]) == lease_token
    assert paused["lease_owner"] == "worker-a"

    assert await repository.heartbeat(
        job_id=first,
        lease_token=lease_token,
        lease_seconds=30,
    ) is True
    assert await repository.resume_job(first) is None

    replacement = await repository.claim_next(
        worker_id="worker-b",
        lease_seconds=30,
        retry_base_seconds=0,
    )
    assert replacement is None, "pause-requested I/O must still consume the global slot"

    assert await repository.lease_is_valid(job_id=first, lease_token=lease_token) is False
    durable = await repository.get_job(first)
    assert durable is not None
    assert durable["status"] == "paused"
    assert durable["lease_token"] is None
    assert durable["lease_owner"] is None

    resumed = await repository.resume_job(first)
    assert resumed is not None and resumed["status"] == "queued"
    assert await repository.claim_next(
        worker_id="worker-b",
        lease_seconds=30,
        retry_base_seconds=0,
    ) is not None


async def test_running_cancel_retains_lease_and_capacity_until_transfer_stops() -> None:
    repository = ModelDownloadRepository()
    first, _ = await _queue_pair(repository, "cancel")

    claim = await repository.claim_next(
        worker_id="worker-a",
        lease_seconds=30,
        retry_base_seconds=0,
    )
    assert claim is not None and claim["job_id"] == first
    lease_token = str(claim["lease_token"])

    cancelled = await repository.cancel_job(first)
    assert cancelled is not None
    assert cancelled["status"] == "running"
    assert cancelled["cancel_requested"] is True
    assert str(cancelled["lease_token"]) == lease_token
    assert cancelled["lease_owner"] == "worker-a"

    assert await repository.heartbeat(
        job_id=first,
        lease_token=lease_token,
        lease_seconds=30,
    ) is True
    assert await repository.claim_next(
        worker_id="worker-b",
        lease_seconds=30,
        retry_base_seconds=0,
    ) is None, "cancel-requested I/O must still consume the global slot"

    assert await repository.lease_is_valid(job_id=first, lease_token=lease_token) is False
    durable = await repository.get_job(first)
    assert durable is not None
    assert durable["status"] == "cancelled"
    assert durable["cancel_requested"] is True
    assert durable["lease_token"] is None
    assert durable["lease_owner"] is None
    assert durable["completed_at"] is not None

    assert await repository.claim_next(
        worker_id="worker-b",
        lease_seconds=30,
        retry_base_seconds=0,
    ) is not None


async def test_failure_after_control_request_finalizes_requested_truth() -> None:
    repository = ModelDownloadRepository()
    cancel_job, pause_job = await _queue_pair(repository, "failure")

    cancel_claim = await repository.claim_next(
        worker_id="worker-a",
        lease_seconds=30,
        retry_base_seconds=0,
    )
    assert cancel_claim is not None and cancel_claim["job_id"] == cancel_job
    cancel_token = str(cancel_claim["lease_token"])
    assert await repository.cancel_job(cancel_job) is not None

    cancelled = await repository.fail_or_retry(
        job_id=cancel_job,
        lease_token=cancel_token,
        error="network failure after cancellation request",
        retry_base_seconds=0,
    )
    assert cancelled is not None
    assert cancelled["status"] == "cancelled"
    assert cancelled["lease_token"] is None
    assert cancelled["error"] is None

    pause_claim = await repository.claim_next(
        worker_id="worker-b",
        lease_seconds=30,
        retry_base_seconds=0,
    )
    assert pause_claim is not None and pause_claim["job_id"] == pause_job
    pause_token = str(pause_claim["lease_token"])
    assert await repository.pause_job(pause_job) is not None

    paused = await repository.fail_or_retry(
        job_id=pause_job,
        lease_token=pause_token,
        error="network failure after pause request",
        retry_base_seconds=0,
    )
    assert paused is not None
    assert paused["status"] == "paused"
    assert paused["lease_token"] is None
    assert paused["error"] is None
