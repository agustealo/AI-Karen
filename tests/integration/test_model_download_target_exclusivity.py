from __future__ import annotations

import asyncio
import os
import uuid
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
        reason="MODEL_DOWNLOAD_TEST_DATABASE_URL is required for PostgreSQL target-exclusivity proofs",
    ),
]


def _payload(job_id: str, install_path: str) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "model_id": "test-owner/shared-target",
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
        "install_path": install_path,
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
            ) VALUES (true, 2)
            ON CONFLICT (singleton) DO UPDATE
            SET max_concurrent_downloads = EXCLUDED.max_concurrent_downloads
            """
        )


async def test_concurrent_create_reuses_one_nonterminal_target_owner() -> None:
    install_path = "/tmp/models/transformers/test-owner--shared-target/main"
    first, second = await asyncio.gather(
        ModelDownloadRepository().create_job(
            _payload("mdl-create-a", install_path),
            max_attempts=3,
        ),
        ModelDownloadRepository().create_job(
            _payload("mdl-create-b", install_path),
            max_attempts=3,
        ),
    )

    assert first["job_id"] == second["job_id"]
    assert {bool(first.get("_target_reused")), bool(second.get("_target_reused"))} == {
        False,
        True,
    }

    jobs = await ModelDownloadRepository().list_jobs(limit=10)
    assert len(jobs) == 1
    assert jobs[0]["install_path"] == install_path


async def test_claim_cancels_legacy_queued_duplicate_and_uses_spare_slot_elsewhere() -> None:
    assert DATABASE_URL is not None
    duplicate_path = "/tmp/models/transformers/test-owner--duplicate/main"
    other_path = "/tmp/models/transformers/test-owner--other/main"
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO public.model_download_jobs (
                job_id, model_id, channel_id, storage_key, status, message,
                install_path, max_attempts, created_at, available_at
            ) VALUES
                (
                    'mdl-duplicate-old', 'test-owner/duplicate',
                    'core_runtime_transformers', 'transformers', 'queued', 'Queued',
                    %s, 3, now() - interval '2 minutes', now() - interval '2 minutes'
                ),
                (
                    'mdl-duplicate-new', 'test-owner/duplicate',
                    'core_runtime_transformers', 'transformers', 'queued', 'Queued',
                    %s, 3, now() - interval '1 minute', now() - interval '1 minute'
                ),
                (
                    'mdl-other', 'test-owner/other',
                    'core_runtime_transformers', 'transformers', 'queued', 'Queued',
                    %s, 3, now(), now()
                )
            """,
            (duplicate_path, duplicate_path, other_path),
        )

    repository = ModelDownloadRepository()
    first = await repository.claim_next(
        worker_id="worker-a",
        lease_seconds=30,
        retry_base_seconds=0,
    )
    second = await repository.claim_next(
        worker_id="worker-b",
        lease_seconds=30,
        retry_base_seconds=0,
    )

    assert first is not None and first["job_id"] == "mdl-duplicate-old"
    assert second is not None and second["job_id"] == "mdl-other"

    superseded = await repository.get_job("mdl-duplicate-new")
    assert superseded is not None
    assert superseded["status"] == "cancelled"
    assert superseded["cancel_requested"] is True
    assert superseded["lease_token"] is None


async def test_promotion_lock_allows_exactly_one_legacy_same_target_lease() -> None:
    assert DATABASE_URL is not None
    install_path = "/tmp/models/transformers/test-owner--promotion-race/main"
    token_a = str(uuid.uuid4())
    token_b = str(uuid.uuid4())
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO public.model_download_jobs (
                job_id, model_id, channel_id, storage_key, status, message,
                install_path, max_attempts, attempt_count, lease_owner, lease_token,
                lease_expires_at, heartbeat_at, started_at, created_at, available_at
            ) VALUES
                (
                    'mdl-promote-a', 'test-owner/promotion-race',
                    'core_runtime_transformers', 'transformers', 'running', 'Downloading',
                    %s, 3, 1, 'worker-a', %s::uuid,
                    now() + interval '30 seconds', now(), now(), now() - interval '2 seconds', now()
                ),
                (
                    'mdl-promote-b', 'test-owner/promotion-race',
                    'core_runtime_transformers', 'transformers', 'running', 'Downloading',
                    %s, 3, 1, 'worker-b', %s::uuid,
                    now() + interval '30 seconds', now(), now(), now() - interval '1 second', now()
                )
            """,
            (install_path, token_a, install_path, token_b),
        )

    first_result, second_result = await asyncio.gather(
        ModelDownloadRepository().lease_is_valid(
            job_id="mdl-promote-a",
            lease_token=token_a,
        ),
        ModelDownloadRepository().lease_is_valid(
            job_id="mdl-promote-b",
            lease_token=token_b,
        ),
    )

    assert sorted((first_result, second_result)) == [False, True]
    first = await ModelDownloadRepository().get_job("mdl-promote-a")
    second = await ModelDownloadRepository().get_job("mdl-promote-b")
    assert first is not None and second is not None
    assert {first["status"], second["status"]} == {"promoting", "cancelled"}

    loser = first if first["status"] == "cancelled" else second
    assert loser["cancel_requested"] is True
    assert loser["lease_token"] is None
    assert loser["completed_at"] is not None


async def test_completion_does_not_mutate_legacy_promoting_sibling() -> None:
    assert DATABASE_URL is not None
    install_path = "/tmp/models/transformers/test-owner--promotion-boundary/main"
    token_a = str(uuid.uuid4())
    token_b = str(uuid.uuid4())
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO public.model_download_jobs (
                job_id, model_id, channel_id, storage_key, status, message,
                install_path, max_attempts, attempt_count, lease_owner, lease_token,
                lease_expires_at, heartbeat_at, started_at, created_at, available_at
            ) VALUES
                (
                    'mdl-boundary-a', 'test-owner/promotion-boundary',
                    'core_runtime_transformers', 'transformers', 'promoting',
                    'Promoting staged artifacts', %s, 3, 1, 'worker-a', %s::uuid,
                    now() + interval '30 seconds', now(), now(), now() - interval '2 seconds', now()
                ),
                (
                    'mdl-boundary-b', 'test-owner/promotion-boundary',
                    'core_runtime_transformers', 'transformers', 'promoting',
                    'Promoting staged artifacts', %s, 3, 1, 'worker-b', %s::uuid,
                    now() + interval '30 seconds', now(), now(), now() - interval '1 second', now()
                )
            """,
            (install_path, token_a, install_path, token_b),
        )

    repository = ModelDownloadRepository()
    completed = await repository.complete_job(
        job_id="mdl-boundary-a",
        lease_token=token_a,
        result_payload={"artifact_path": install_path},
        install_path=install_path,
    )

    assert completed is not None
    assert completed["status"] == "completed"

    sibling = await repository.get_job("mdl-boundary-b")
    assert sibling is not None
    assert sibling["status"] == "promoting"
    assert sibling["cancel_requested"] is False
    assert str(sibling["lease_token"]) == token_b
    assert sibling["message"] == "Promoting staged artifacts"


async def test_publication_guard_rejects_lease_expired_while_waiting_for_target_lock() -> None:
    assert DATABASE_URL is not None
    install_path = "/tmp/models/transformers/test-owner--publication-wait/main"
    token = str(uuid.uuid4())
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO public.model_download_jobs (
                job_id, model_id, channel_id, storage_key, status, message,
                install_path, max_attempts, attempt_count, lease_owner, lease_token,
                lease_expires_at, heartbeat_at, started_at, created_at, available_at
            ) VALUES (
                'mdl-publication-wait', 'test-owner/publication-wait',
                'core_runtime_transformers', 'transformers', 'promoting',
                'Promoting staged artifacts', %s, 3, 1, 'worker-a', %s::uuid,
                now() + interval '1 second', now(), now(), now(), now()
            )
            """,
            (install_path, token),
        )

    blocker = psycopg.connect(DATABASE_URL)
    try:
        blocker.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (install_path,),
        )

        async def attempt_publication() -> bool:
            async with ModelDownloadRepository().publication_guard(
                job_id="mdl-publication-wait",
                lease_token=token,
                install_path=install_path,
            ) as publication:
                return publication is not None

        publication_task = asyncio.create_task(attempt_publication())
        await asyncio.sleep(1.2)
        assert publication_task.done() is False
        blocker.commit()
        assert await asyncio.wait_for(publication_task, timeout=2.0) is False
    finally:
        blocker.close()

    durable = await ModelDownloadRepository().get_job("mdl-publication-wait")
    assert durable is not None
    assert durable["status"] == "promoting"
    assert str(durable["lease_token"]) == token


async def test_publication_guard_denies_all_reclaim_authority_until_guard_releases() -> None:
    assert DATABASE_URL is not None
    install_path = "/tmp/models/transformers/test-owner--publication-guard/main"
    token = str(uuid.uuid4())
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO public.model_download_jobs (
                job_id, model_id, channel_id, storage_key, status, message,
                install_path, max_attempts, attempt_count, lease_owner, lease_token,
                lease_expires_at, heartbeat_at, started_at, created_at, available_at
            ) VALUES (
                'mdl-publication-guard', 'test-owner/publication-guard',
                'core_runtime_transformers', 'transformers', 'promoting',
                'Promoting staged artifacts', %s, 3, 1, 'worker-a', %s::uuid,
                now() + interval '1 second', now(), now(), now(), now()
            )
            """,
            (install_path, token),
        )

    repository = ModelDownloadRepository()
    async with repository.publication_guard(
        job_id="mdl-publication-guard",
        lease_token=token,
        install_path=install_path,
    ) as publication:
        assert publication is not None
        await asyncio.sleep(1.2)

        ordinary = await ModelDownloadRepository().claim_next(
            worker_id="ordinary-worker",
            lease_seconds=30,
            retry_base_seconds=0,
        )
        recovery = await ModelDownloadRepository().claim_expired_promotion_for_recovery(
            worker_id="recovery-worker",
            lease_seconds=30,
        )

        assert ordinary is None
        assert recovery is None
        durable_inside = await ModelDownloadRepository().get_job("mdl-publication-guard")
        assert durable_inside is not None
        assert durable_inside["status"] == "promoting"
        assert str(durable_inside["lease_token"]) == token

    recovered = await ModelDownloadRepository().claim_expired_promotion_for_recovery(
        worker_id="recovery-worker",
        lease_seconds=30,
    )
    assert recovered is not None
    assert recovered["job_id"] == "mdl-publication-guard"
    assert recovered["interrupted_lease_token"] == token
    assert str(recovered["lease_token"]) != token
    assert recovered["status"] == "promoting"
