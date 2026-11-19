"""Canonical ArtifactStore adapter contract for the standalone File Explorer."""
from __future__ import annotations

import asyncio
import importlib.util
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
FILE = ROOT / "src/ai_karen_engine/extensions/plugins/file-explorer/artifact_source.py"
SPEC = importlib.util.spec_from_file_location("file_explorer_artifact_source", FILE)
assert SPEC is not None and SPEC.loader is not None
SOURCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOURCE)

TENANT = str(uuid.uuid4())
OWNER = str(uuid.uuid4())
OTHER_OWNER = str(uuid.uuid4())
OTHER_TENANT = str(uuid.uuid4())
ARTIFACT_ID = str(uuid.uuid4())
SHA = "a" * 64


@dataclass
class SourceRecord:
    id: str = ARTIFACT_ID
    tenant_id: str = TENANT
    user_id: str = OWNER
    filename: str = "report.txt"
    size_bytes: int = 1024
    sha256: str = SHA
    deleted_at: datetime | None = None
    storage_key: str = "private/never-return"


class Repository:
    def __init__(self, records: list[SourceRecord] | None = None, *, fails: bool = False):
        self.records = [SourceRecord()] if records is None else records
        self.fails = fails
        self.list_calls: list[str] = []
        self.metadata_calls: list[tuple[str, str]] = []

    async def list_artifacts(self, tenant_id, conversation_id=None, message_id=None):
        self.list_calls.append(tenant_id)
        return SimpleNamespace(success=not self.fails, data=self.records)

    async def get_metadata(self, artifact_id, tenant_id):
        self.metadata_calls.append((artifact_id, tenant_id))
        item = next((r for r in self.records if r.id == artifact_id), None)
        return SimpleNamespace(success=not self.fails, data=item)


def run(coro):
    return asyncio.run(coro)


def test_owner_list_excludes_other_users_and_tenants():
    repo = Repository([
        SourceRecord(),
        SourceRecord(id=str(uuid.uuid4()), user_id=OTHER_OWNER),
        SourceRecord(id=str(uuid.uuid4()), tenant_id=OTHER_TENANT),
        SourceRecord(id=str(uuid.uuid4()), deleted_at=datetime.utcnow()),
    ])
    adapter = SOURCE.ArtifactSourceAdapter(repo)
    found = run(adapter.list_owner_sources(tenant_id=TENANT, user_id=OWNER))
    assert len(found) == 1
    assert found[0]["source_id"] == ARTIFACT_ID
    assert found[0]["revision"] == SHA
    assert "storage_key" not in found[0]
    assert repo.list_calls == [TENANT]


def test_revalidation_checks_latest_canonical_metadata():
    repo = Repository()
    adapter = SOURCE.ArtifactSourceAdapter(repo)
    result = run(adapter.revalidate_owner_reference(
        tenant_id=TENANT, user_id=OWNER,
        source_id=ARTIFACT_ID, expected_revision=SHA,
    ))
    assert result["owner_scope_verified"] is True
    assert result["access_semantics"] == "owner_only_at_lookup_time_not_transferable_grant"
    assert "storage_key" not in result
    repo.records[0].sha256 = "b" * 64
    with pytest.raises(PermissionError, match="revision_changed"):
        run(adapter.revalidate_owner_reference(
            tenant_id=TENANT, user_id=OWNER,
            source_id=ARTIFACT_ID, expected_revision=SHA,
        ))


def test_removed_owner_and_deleted_source_denied():
    repo = Repository()
    adapter = SOURCE.ArtifactSourceAdapter(repo)
    repo.records[0].user_id = OTHER_OWNER
    with pytest.raises(PermissionError, match="source_unavailable"):
        run(adapter.revalidate_owner_reference(
            tenant_id=TENANT, user_id=OWNER,
            source_id=ARTIFACT_ID, expected_revision=SHA,
        ))
    repo.records[0].user_id = OWNER
    repo.records[0].deleted_at = datetime.utcnow()
    with pytest.raises(PermissionError, match="source_unavailable"):
        run(adapter.revalidate_owner_reference(
            tenant_id=TENANT, user_id=OWNER,
            source_id=ARTIFACT_ID, expected_revision=SHA,
        ))


def test_missing_metadata_and_storage_failure_fail_closed():
    for records, fails in [([], False), ([SourceRecord()], True)]:
        repo = Repository(records, fails=fails)
        adapter = SOURCE.ArtifactSourceAdapter(repo)
        with pytest.raises(PermissionError):
            run(adapter.revalidate_owner_reference(
                tenant_id=TENANT, user_id=OWNER,
                source_id=ARTIFACT_ID, expected_revision=SHA,
            ))
        if fails:
            with pytest.raises(RuntimeError, match="artifact_list_unavailable"):
                run(adapter.list_owner_sources(tenant_id=TENANT, user_id=OWNER))
        else:
            assert run(adapter.list_owner_sources(tenant_id=TENANT, user_id=OWNER)) == []


def test_limits_reject_incomplete_owner_snapshots():
    records = [SourceRecord(id=str(uuid.uuid4())) for _ in range(201)]
    with pytest.raises(RuntimeError, match="pagination_required"):
        run(SOURCE.ArtifactSourceAdapter(Repository(records)).list_owner_sources(
            tenant_id=TENANT, user_id=OWNER
        ))


@pytest.mark.parametrize("tenant_id,user_id", [
    ("default", OWNER),
    (TENANT, "default"),
    (OTHER_TENANT, ""),
])
def test_unscoped_lookup_does_not_touch_storage(tenant_id, user_id):
    repo = Repository()
    with pytest.raises(PermissionError):
        run(SOURCE.ArtifactSourceAdapter(repo).list_owner_sources(
            tenant_id=tenant_id, user_id=user_id
        ))
    assert repo.list_calls == []


def test_cross_tenant_and_wrong_source_id_denied():
    repo = Repository()
    with pytest.raises(PermissionError):
        run(SOURCE.ArtifactSourceAdapter(repo).revalidate_owner_reference(
            tenant_id=OTHER_TENANT, user_id=OWNER,
            source_id=ARTIFACT_ID, expected_revision=SHA,
        ))
    assert repo.metadata_calls == [(ARTIFACT_ID, OTHER_TENANT)]


def test_invalid_metadata_and_duplicate_records_denied():
    repo = Repository([SourceRecord(sha256="unknown")])
    with pytest.raises(ValueError):
        run(SOURCE.ArtifactSourceAdapter(repo).list_owner_sources(
            tenant_id=TENANT, user_id=OWNER
        ))
    repo.records = [SourceRecord(), SourceRecord()]
    with pytest.raises(RuntimeError, match="duplicate_artifact"):
        run(SOURCE.ArtifactSourceAdapter(repo).list_owner_sources(
            tenant_id=TENANT, user_id=OWNER
        ))
