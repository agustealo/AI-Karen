"""Real PostgreSQL proof for privacy-safe owned model-download failure diagnostics.

The underlying worker exception may contain paths, access tokens or upstream
URLs. Only a small operator-facing category may escape the SQL owned projection.
This test requires the disposable model-download CI database and its migrations.
"""

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
        reason="MODEL_DOWNLOAD_TEST_DATABASE_URL is required for scoped PostgreSQL proof",
    ),
]


async def test_owned_failure_categories_and_cross_tenant_sql_isolation() -> None:
    assert DATABASE_URL is not None
    tenant = str(uuid.uuid4())
    other_tenant = str(uuid.uuid4())
    owner = str(uuid.uuid4())
    other_user = str(uuid.uuid4())
    private_marker = "DO_NOT_LEAK_PRIVATE_PATH_OR_TOKEN"
    cases = (
        ("access", "failed", f"403 gated access denied {private_marker}", "source_access"),
        ("network", "failed", f"ConnectTimeout on upstream {private_marker}", "network"),
        ("storage", "failed", f"no space left on volume {private_marker}", "storage"),
        ("integrity", "failed", f"checksum mismatch {private_marker}", "integrity"),
        ("unknown", "failed", f"InternalWorkerError {private_marker}", "unknown"),
        ("cancelled", "cancelled", f"403 gated {private_marker}", "cancelled"),
        ("queued", "queued", f"403 gated {private_marker}", None),
    )
    jobs = [
        (f"mdl-{uuid.uuid4()}", status, error, expected, tag)
        for tag, status, error, expected in cases
    ]
    hidden = [f"mdl-{uuid.uuid4()}" for _ in range(2)]
    all_ids = [j[0] for j in jobs] + hidden

    try:
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            for job_id, status, error, _, tag in jobs:
                connection.execute(
                    """
                    INSERT INTO public.model_download_jobs (
                        job_id, model_id, channel_id, tenant_id, requested_by,
                        status, error, message
                    ) VALUES (%s, %s, 'plugin_audio', %s, %s, %s, %s, %s)
                    """,
                    (
                        job_id,
                        f"test-owner/failure-{tag}",
                        tenant,
                        owner,
                        status,
                        error,
                        f"Worker message {private_marker}",
                    ),
                )
            for index, job_id in enumerate(hidden):
                connection.execute(
                    """
                    INSERT INTO public.model_download_jobs (
                        job_id, model_id, channel_id, tenant_id, requested_by,
                        status, error, message
                    ) VALUES (%s, 'test-owner/private', 'plugin_audio',
                              %s, %s, 'failed', %s, %s)
                    """,
                    (
                        job_id,
                        other_tenant if index == 0 else tenant,
                        owner if index == 0 else other_user,
                        f"403 secret {private_marker}",
                        f"Message {private_marker}",
                    ),
                )

        repo = ModelDownloadRepository()
        result = await repo.list_owned_jobs(tenant_id=tenant, user_id=owner, limit=200)
        expected_map = {job_id: expected for job_id, _, _, expected, _ in jobs}
        owned = [row for row in result if row["job_id"] in all_ids]
        assert {row["job_id"] for row in owned} == set(expected_map)
        for row in owned:
            assert row["failure_category"] == expected_map[row["job_id"]]
            assert not ({"error", "message", "install_path", "lease_token", "storage_key"} & set(row))
            assert private_marker not in repr(row)

        for job_id, _, _, expected, _ in jobs:
            single = await repo.get_owned_job(
                job_id=job_id, tenant_id=tenant, user_id=owner
            )
            assert single is not None
            assert single["failure_category"] == expected
            assert not ({"error", "message", "install_path", "lease_token", "storage_key"} & set(single))
            assert private_marker not in repr(single)

        for job_id in hidden:
            assert await repo.get_owned_job(
                job_id=job_id, tenant_id=tenant, user_id=owner
            ) is None
        assert await repo.list_owned_jobs(
            tenant_id=str(uuid.uuid4()), user_id=owner
        ) == []
    finally:
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            connection.execute(
                "DELETE FROM public.model_download_jobs WHERE job_id = ANY(%s)",
                (all_ids,),
            )
