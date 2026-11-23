"""Canonical artifact upload compensation and storage-key regression tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.services.database.repositories.artifact_store import ArtifactUploadRequest
from ai_karen_engine.services.database.repositories.supabase_artifact_store import SupabaseArtifactStore


class Bucket:
    def __init__(self):
        self.objects = {}
        self.removals = []

    def upload(self, key, data, options):
        self.objects[key] = data

    def remove(self, keys):
        self.removals.extend(keys)
        for key in keys:
            self.objects.pop(key, None)


class Session:
    def __init__(self, failure=None):
        self.failure = failure
        self.queries = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, statement, params):
        self.queries.append(params)
        if self.failure == "insert":
            raise RuntimeError("database insert failed")

    async def commit(self):
        self.commits += 1
        if self.failure == "commit":
            raise RuntimeError("commit outcome unknown")


def make_store(session):
    bucket = Bucket()
    storage = SimpleNamespace(from_=lambda name: bucket)
    store = SupabaseArtifactStore(
        session_factory=lambda: session,
        storage_client=SimpleNamespace(storage=storage),
    )
    return store, bucket


def request(filename="../../private.txt"):
    return ArtifactUploadRequest(
        tenant_id="tenant-a",
        user_id="owner-a",
        filename=filename,
        content_type="text/plain",
        data=b"verified",
    )


@pytest.mark.asyncio
async def test_uploaded_object_uses_opaque_key_and_retains_display_name():
    session = Session()
    store, bucket = make_store(session)
    result = await store.upload(request())
    assert result.success
    artifact = result.data
    assert artifact.filename == "../../private.txt"
    assert artifact.storage_key.endswith("/content")
    assert "../../" not in artifact.storage_key
    assert bucket.objects[artifact.storage_key] == b"verified"
    assert session.queries[0]["storage_uri"].endswith("/content")
    assert session.commits == 1


@pytest.mark.asyncio
async def test_failed_insert_compensates_storage_object():
    session = Session(failure="insert")
    store, bucket = make_store(session)
    result = await store.upload(request("file.txt"))
    assert not result.success
    assert result.error == "artifact_commit_failed"
    assert bucket.objects == {}
    assert len(bucket.removals) == 1
    assert session.commits == 0


@pytest.mark.asyncio
async def test_uncertain_commit_preserves_object_for_reconciliation():
    session = Session(failure="commit")
    store, bucket = make_store(session)
    result = await store.upload(request("file.txt"))
    assert not result.success
    assert result.error == "artifact_commit_failed"
    assert len(bucket.objects) == 1
    assert bucket.removals == []
    assert session.commits == 1
