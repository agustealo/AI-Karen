from __future__ import annotations

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
        reason="MODEL_DOWNLOAD_TEST_DATABASE_URL is required for terminal-cleanup proofs",
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
            ) VALUES (true, 1)
            ON CONFLICT (singleton) DO UPDATE
            SET max_concurrent_downloads = EXCLUDED.max_concurrent_downloads
            """
        )


async def test_completion_retains_cleanup_identity_until_acknowledged() -> None:
    assert DATABASE_URL is not None
    repository = ModelDownloadRepository()
    job_id = "mdl-terminal-cleanup"
    install_path = "/tmp/models/transformers/test-owner--terminal-cleanup/main"
    source_token = str(uuid.uuid4())

    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO public.model_download_jobs (
                job_id, model_id, channel_id, storage_key, status, message,
                install_path, max_attempts, attempt_count, lease_owner, lease_token,
                lease_expires_at, heartbeat_at, started_at, created_at, available_at
            ) VALUES (
                %s, 'test-owner/terminal-cleanup',
                'core_runtime_transformers', 'transformers', 'running',
                'Downloading', %s, 3, 1, 'worker-a', %s::uuid,
                clock_timestamp() + interval '30 seconds', clock_timestamp(),
                clock_timestamp(), clock_timestamp(), clock_timestamp()
            )
            """,
            (job_id, install_path, source_token),
        )

    assert await repository.lease_is_valid(job_id=job_id, lease_token=source_token) is True
    reserved = await repository.get_job(job_id)
    assert reserved is not None
    assert reserved["status"] == "promoting"
    assert str(reserved["publication_source_lease_token"]) == source_token

    async with repository.publication_guard(
        job_id=job_id,
        lease_token=source_token,
        install_path=install_path,
    ) as publication:
        assert publication is not None
        completed = await publication.complete(
            {"status": "success", "install_path": install_path}
        )

    assert completed["status"] == "completed"
    assert completed["lease_token"] is None
    assert str(completed["publication_source_lease_token"]) == source_token

    candidates = await repository.list_completed_publication_cleanup_candidates(limit=10)
    assert [row["job_id"] for row in candidates] == [job_id]
    assert str(candidates[0]["publication_source_lease_token"]) == source_token

    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(
            """
            UPDATE public.model_download_jobs
            SET updated_at = clock_timestamp() - interval '2 days'
            WHERE job_id = %s
            """,
            (job_id,),
        )

    assert await repository.cleanup_finished_jobs(max_age_seconds=1) == 0
    assert await repository.get_job(job_id) is not None

    assert await repository.acknowledge_publication_cleanup(
        job_id=job_id,
        source_lease_token=source_token,
    ) is True
    acknowledged = await repository.get_job(job_id)
    assert acknowledged is not None
    assert acknowledged["publication_source_lease_token"] is None

    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(
            """
            UPDATE public.model_download_jobs
            SET updated_at = clock_timestamp() - interval '2 days'
            WHERE job_id = %s
            """,
            (job_id,),
        )

    assert await repository.cleanup_finished_jobs(max_age_seconds=1) == 1
    assert await repository.get_job(job_id) is None


async def test_cleanup_ack_is_source_identity_fenced() -> None:
    assert DATABASE_URL is not None
    repository = ModelDownloadRepository()
    source_token = str(uuid.uuid4())
    other_token = str(uuid.uuid4())
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO public.model_download_jobs (
                job_id, model_id, channel_id, status, message, install_path,
                max_attempts, progress, publication_source_lease_token, completed_at
            ) VALUES (
                'mdl-cleanup-fence', 'test-owner/cleanup-fence',
                'core_runtime_transformers', 'completed', 'Download completed',
                '/tmp/models/transformers/test-owner--cleanup-fence/main',
                3, 1.0, %s::uuid, clock_timestamp()
            )
            """,
            (source_token,),
        )

    assert await repository.acknowledge_publication_cleanup(
        job_id="mdl-cleanup-fence",
        source_lease_token=other_token,
    ) is False
    durable = await repository.get_job("mdl-cleanup-fence")
    assert durable is not None
    assert str(durable["publication_source_lease_token"]) == source_token
