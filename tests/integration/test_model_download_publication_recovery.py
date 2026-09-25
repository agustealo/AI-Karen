from __future__ import annotations

import asyncio
import os
import uuid

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
        reason="MODEL_DOWNLOAD_TEST_DATABASE_URL is required for PostgreSQL publication-recovery proofs",
    ),
]


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


def _insert_expired_promotion(
    *,
    job_id: str,
    install_path: str,
    lease_token: str,
) -> None:
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO public.model_download_jobs (
                job_id, model_id, channel_id, storage_key, status, message,
                install_path, max_attempts, attempt_count, lease_owner, lease_token,
                lease_expires_at, heartbeat_at, started_at, created_at, available_at
            ) VALUES (
                %s, 'test-owner/recovery-target',
                'core_runtime_transformers', 'transformers', 'promoting',
                'Promoting staged artifacts', %s, 3, 1, 'dead-worker', %s::uuid,
                clock_timestamp() - interval '5 seconds',
                clock_timestamp() - interval '10 seconds',
                clock_timestamp() - interval '20 seconds',
                clock_timestamp() - interval '30 seconds',
                clock_timestamp() - interval '30 seconds'
            )
            """,
            (job_id, install_path, lease_token),
        )


async def test_concurrent_recovery_claims_issue_exactly_one_new_lease() -> None:
    install_path = "/tmp/models/transformers/test-owner--recovery-target/main"
    source_token = str(uuid.uuid4())
    _insert_expired_promotion(
        job_id="mdl-recovery-race",
        install_path=install_path,
        lease_token=source_token,
    )

    first, second = await asyncio.gather(
        ModelDownloadRepository().claim_expired_promotion_for_recovery(
            worker_id="recovery-a",
            lease_seconds=30,
        ),
        ModelDownloadRepository().claim_expired_promotion_for_recovery(
            worker_id="recovery-b",
            lease_seconds=30,
        ),
    )

    claims = [claim for claim in (first, second) if claim is not None]
    assert len(claims) == 1
    claim = claims[0]
    assert claim["job_id"] == "mdl-recovery-race"
    assert claim["status"] == "promoting"
    assert claim["interrupted_lease_token"] == source_token
    assert str(claim["lease_token"]) != source_token
    assert claim["lease_owner"] in {"recovery-a", "recovery-b"}


async def test_generic_claim_cannot_requeue_or_bypass_expired_promotion_target() -> None:
    assert DATABASE_URL is not None
    blocked_path = "/tmp/models/transformers/test-owner--recovery-target/main"
    other_path = "/tmp/models/transformers/test-owner--other/main"
    source_token = str(uuid.uuid4())
    _insert_expired_promotion(
        job_id="mdl-interrupted",
        install_path=blocked_path,
        lease_token=source_token,
    )
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO public.model_download_jobs (
                job_id, model_id, channel_id, storage_key, status, message,
                install_path, max_attempts, created_at, available_at
            ) VALUES
                (
                    'mdl-blocked-sibling', 'test-owner/recovery-target',
                    'core_runtime_transformers', 'transformers', 'queued', 'Queued',
                    %s, 3, clock_timestamp() - interval '2 seconds', clock_timestamp()
                ),
                (
                    'mdl-unrelated', 'test-owner/other',
                    'core_runtime_transformers', 'transformers', 'queued', 'Queued',
                    %s, 3, clock_timestamp() - interval '1 second', clock_timestamp()
                )
            """,
            (blocked_path, other_path),
        )

    repository = ModelDownloadRepository()
    normal = await repository.claim_next(
        worker_id="normal-worker",
        lease_seconds=30,
        retry_base_seconds=0,
    )

    assert normal is not None and normal["job_id"] == "mdl-unrelated"
    interrupted = await repository.get_job("mdl-interrupted")
    blocked = await repository.get_job("mdl-blocked-sibling")
    assert interrupted is not None
    assert interrupted["status"] == "promoting"
    assert str(interrupted["lease_token"]) == source_token
    assert blocked is not None and blocked["status"] == "queued"
    assert blocked["lease_token"] is None

    recovery = await repository.claim_expired_promotion_for_recovery(
        worker_id="recovery-worker",
        lease_seconds=30,
    )
    assert recovery is not None
    assert recovery["job_id"] == "mdl-interrupted"
    assert recovery["interrupted_lease_token"] == source_token


async def test_release_for_recovery_expires_authority_without_erasing_receipt_identity() -> None:
    install_path = "/tmp/models/transformers/test-owner--recovery-target/main"
    source_token = str(uuid.uuid4())
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO public.model_download_jobs (
                job_id, model_id, channel_id, storage_key, status, message,
                install_path, max_attempts, attempt_count, lease_owner, lease_token,
                lease_expires_at, heartbeat_at, started_at, created_at, available_at
            ) VALUES (
                'mdl-release-recovery', 'test-owner/recovery-target',
                'core_runtime_transformers', 'transformers', 'promoting',
                'Promoting staged artifacts', %s, 3, 1, 'worker-a', %s::uuid,
                clock_timestamp() + interval '30 seconds', clock_timestamp(),
                clock_timestamp(), clock_timestamp(), clock_timestamp()
            )
            """,
            (install_path, source_token),
        )

    repository = ModelDownloadRepository()
    released = await repository.release_publication_for_recovery(
        job_id="mdl-release-recovery",
        lease_token=source_token,
        error="commit uncertain",
    )
    assert released is True

    claimed = await repository.claim_expired_promotion_for_recovery(
        worker_id="recovery-worker",
        lease_seconds=30,
    )
    assert claimed is not None
    assert claimed["interrupted_lease_token"] == source_token
    assert str(claimed["lease_token"]) != source_token
