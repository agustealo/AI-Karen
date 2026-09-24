from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ai_karen_engine.services.auth.auth_service import UserStatus
from ai_karen_engine.services.automation.legacy_job_migration import (
    LegacyAutomationMigrationError,
    LegacyAutomationMigrationRequired,
    assert_legacy_job_cutover_complete,
    migrate_legacy_jobs,
)

TENANT_ID = "00000000-0000-0000-0000-000000000001"
USER_ID = "00000000-0000-0000-0000-000000000002"


class FakeAuth:
    def __init__(self, tenant_id=TENANT_ID):
        self.account = SimpleNamespace(
            id=USER_ID,
            tenant_id=tenant_id,
            status=UserStatus.ACTIVE,
        )

    async def list_users(self, *, tenant_id, limit, offset):
        if tenant_id != self.account.tenant_id:
            return []
        return [self.account]


class FakeRepository:
    def __init__(self):
        self.jobs = {}

    async def get_job(self, job_id, tenant_id):
        record = self.jobs.get(job_id)
        if record and record["tenant_id"] == tenant_id:
            return record
        return None

    async def create_job(self, *, tenant_id, created_by, record):
        stored = dict(record)
        stored["tenant_id"] = tenant_id
        stored["created_by"] = created_by
        self.jobs[record["id"]] = stored
        return stored


def _write_legacy(path):
    path.write_text(
        json.dumps(
            {
                "job_keep_id": {
                    "id": "job_keep_id",
                    "name": "Legacy job",
                    "description": "Preserve me",
                    "tasks": [{"name": "Step", "agent": "assistant"}],
                    "trigger": "Manual Run",
                    "status": "Running",
                    "created_at": "2026-09-01T12:00:00",
                    "updated_at": "2026-09-01T12:10:00",
                }
            }
        ),
        encoding="utf-8",
    )


def test_nonempty_legacy_store_blocks_silent_cutover(tmp_path):
    source = tmp_path / "automation_jobs.json"
    _write_legacy(source)

    with pytest.raises(LegacyAutomationMigrationRequired):
        assert_legacy_job_cutover_complete(source)


@pytest.mark.asyncio
async def test_migration_preserves_job_id_and_removes_source_after_verification(tmp_path):
    source = tmp_path / "automation_jobs.json"
    _write_legacy(source)
    repo = FakeRepository()

    result = await migrate_legacy_jobs(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        source_path=source,
        repository=repo,
        auth_service=FakeAuth(),
    )

    assert result.imported == 1
    assert result.already_present == 0
    assert result.removed_source is True
    assert not source.exists()
    assert "job_keep_id" in repo.jobs
    assert repo.jobs["job_keep_id"]["id"] == "job_keep_id"
    assert repo.jobs["job_keep_id"]["tenant_id"] == TENANT_ID
    assert repo.jobs["job_keep_id"]["created_by"] == USER_ID
    assert repo.jobs["job_keep_id"]["status"] == "Pending"


@pytest.mark.asyncio
async def test_migration_refuses_owner_from_another_tenant_and_keeps_source(tmp_path):
    source = tmp_path / "automation_jobs.json"
    _write_legacy(source)

    with pytest.raises(LegacyAutomationMigrationError):
        await migrate_legacy_jobs(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            source_path=source,
            repository=FakeRepository(),
            auth_service=FakeAuth(
                tenant_id="00000000-0000-0000-0000-000000000099"
            ),
        )

    assert source.exists()
