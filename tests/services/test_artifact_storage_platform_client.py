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
