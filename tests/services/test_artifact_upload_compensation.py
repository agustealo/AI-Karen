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
        self.uploads = []

    def upload(self, key, data, options):
        self.uploads.append((key, data, options))
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



@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "insert", "commit"])
async def test_reserved_writer_consumes_claim_and_never_compensates(monkeypatch, failure):
    from hashlib import sha256
    from unittest.mock import AsyncMock
    from uuid import uuid4
    from ai_karen_engine.services.database.repositories import supabase_artifact_store as module

    tenant, owner, session_id, token = (str(uuid4()) for _ in range(4))
    session = Session(failure=failure)
    store, bucket = make_store(session)
    calls = SimpleNamespace(
        consume_write_claim=AsyncMock(return_value=SimpleNamespace(state="reconcile_required")),
        reconcile_verified_text=AsyncMock(return_value=SimpleNamespace(
            state="committed", artifact_id=session_id,
        )),
    )
    monkeypatch.setattr(module, "UploadSessionRepository", lambda factory: calls)
    upload = ArtifactUploadRequest(
        tenant_id=tenant, user_id=owner, filename="generated.txt",
        content_type="text/plain", data=b"verified",
    )
    result = await store.upload_reserved_text(upload, session_id=session_id, lease_token=token)
    calls.consume_write_claim.assert_awaited_once_with(
        tenant_id=tenant, owner_user_id=owner, session_id=session_id, lease_token=token,
        observed_bytes=len(upload.data), observed_sha256=sha256(upload.data).hexdigest(),
    )
    key = f"{tenant}/{session_id}/content"
    assert bucket.uploads == [(key, b"verified", {"content-type": "text/plain", "upsert": "false"})]
    assert bucket.objects[key] == b"verified"
    assert bucket.removals == []
    if failure is None:
        assert result.success and result.data.id == session_id
        calls.reconcile_verified_text.assert_awaited_once_with(
            tenant_id=tenant, owner_user_id=owner, session_id=session_id, artifact_store=store,
        )
    else:
        assert not result.success and result.error == "reserved_upload_reconcile_required"
        calls.reconcile_verified_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_reserved_writer_denies_replay_and_unverified_readback(monkeypatch):
    from unittest.mock import AsyncMock
    from uuid import uuid4
    from ai_karen_engine.services.database.repositories import supabase_artifact_store as module

    tenant, owner, session_id, token = (str(uuid4()) for _ in range(4))
    db = Session()
    store, bucket = make_store(db)
    ledger = SimpleNamespace(
        consume_write_claim=AsyncMock(side_effect=[SimpleNamespace(state="reconcile_required"), None]),
        reconcile_verified_text=AsyncMock(return_value=None),
    )
    monkeypatch.setattr(module, "UploadSessionRepository", lambda factory: ledger)
    upload = ArtifactUploadRequest(
        tenant_id=tenant, user_id=owner, filename="generated.md",
        content_type="text/plain", data=b"verified",
    )
    first = await store.upload_reserved_text(upload, session_id=session_id, lease_token=token)
    second = await store.upload_reserved_text(upload, session_id=session_id, lease_token=token)
    assert not first.success and first.error == "reserved_upload_reconcile_required"
    assert not second.success
    assert len(bucket.uploads) == 1 and bucket.removals == []
    ledger.reconcile_verified_text.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("filename,data", [
    ("../../private.txt", b"valid"), ("run.html", b"valid"),
    ("generated.txt", b""), ("generated.txt", b"\xff"),
    ("generated.txt", b"x" * 65537), ("generated.txt", b"\x00"),
])
async def test_reserved_writer_rejects_invalid_content_before_claim(monkeypatch, filename, data):
    from uuid import uuid4
    from ai_karen_engine.services.database.repositories import supabase_artifact_store as module

    tenant, owner, session_id, token = (str(uuid4()) for _ in range(4))
    store, bucket = make_store(Session())
    def forbidden(factory):
        raise AssertionError("invalid input must not reach the ledger")
    monkeypatch.setattr(module, "UploadSessionRepository", forbidden)
    upload = ArtifactUploadRequest(
        tenant_id=tenant, user_id=owner, filename=filename,
        content_type="text/plain", data=data,
    )
    result = await store.upload_reserved_text(upload, session_id=session_id, lease_token=token)
    assert not result.success and result.error == "reserved_upload_unavailable"
    assert not bucket.uploads
