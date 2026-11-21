"""Prove artifact storage uses the initialized canonical platform bucket."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.services.database.repositories.supabase_artifact_store import (
    SupabaseArtifactStore,
)


class FakeBucket:
    def __init__(self):
        self.files = {}

    def upload(self, key, data, options):
        self.files[key] = data

    def download(self, key):
        return self.files[key]

    def remove(self, keys):
        for key in keys:
            self.files.pop(key)


class FakeStorage:
    def __init__(self):
        self.bucket = FakeBucket()
        self.requested = []

    def from_(self, name):
        self.requested.append(name)
        return self.bucket


def test_artifact_bucket_reuses_platform_storage_client():
    storage = FakeStorage()
    client = SimpleNamespace(storage=storage)
    store = SupabaseArtifactStore(session_factory=None, storage_client=client)
    bucket = store._bucket()
    bucket.upload("tenant/article.txt", b"article", {"content-type": "text/plain"})
    assert store._bucket().download("tenant/article.txt") == b"article"
    store._bucket().remove(["tenant/article.txt"])
    assert storage.requested == ["artifacts", "artifacts", "artifacts"]
    assert not storage.bucket.files


def test_artifact_bucket_requires_initialized_storage_capability():
    store = SupabaseArtifactStore(
        session_factory=None, storage_client=SimpleNamespace(storage=None)
    )
    with pytest.raises(RuntimeError, match="unavailable"):
        store._bucket()


@pytest.mark.asyncio
async def test_bounded_owner_text_read_fails_closed_when_backend_cannot_stream():
    """A whole-object Supabase download cannot masquerade as a byte cap."""
    storage = FakeStorage()
    store = SupabaseArtifactStore(
        session_factory=None, storage_client=SimpleNamespace(storage=storage)
    )
    result = await store.read_owner_active_text_bounded(
        "c3354c0f-4350-4562-96f8-64d1f8c8783b",
        "d2fb0a60-b773-439b-8268-638a88c58e14",
        "9ba9d98c-e9ca-461c-a595-3ef7f0d19fe4",
        max_bytes=65536,
    )
    assert result.success is False
    assert result.data is None
    assert result.error == "bounded_artifact_read_unavailable"
    # The repository must not even initialize the bucket or fetch storage
    # objects when the backend cannot guarantee bounded transfer.
    assert storage.requested == []


@pytest.mark.asyncio
async def test_bounded_owner_text_read_does_not_fetch_oversize_object():
    class DangerousBucket(FakeBucket):
        def download(self, key):
            raise AssertionError("unbounded bucket.download must never run")

    storage = FakeStorage()
    storage.bucket = DangerousBucket()
    store = SupabaseArtifactStore(
        session_factory=None, storage_client=SimpleNamespace(storage=storage)
    )
    result = await store.read_owner_active_text_bounded(
        "c3354c0f-4350-4562-96f8-64d1f8c8783b",
        "d2fb0a60-b773-439b-8268-638a88c58e14",
        "9ba9d98c-e9ca-461c-a595-3ef7f0d19fe4",
        max_bytes=1,
    )
    assert not result.success
    assert result.data is None
    assert storage.requested == []
