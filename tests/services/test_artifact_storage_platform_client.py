"""Prove artifact storage uses the initialized canonical platform bucket."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import hashlib

import httpx

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


_ARTIFACT = "c3354c0f-4350-4562-96f8-64d1f8c8783b"
_TENANT = "d2fb0a60-b773-439b-8268-638a88c58e14"
_OWNER = "9ba9d98c-e9ca-461c-a595-3ef7f0d19fe4"
_BODY = b"These are the original author's words."


class SignedBucket(FakeBucket):
    def __init__(self, signed_url=None):
        super().__init__()
        self.signed_url = signed_url
        self.signatures = []

    def download(self, key):
        raise AssertionError("full-buffer download forbidden")

    def create_signed_url(self, key, expiry):
        self.signatures.append((key, expiry))
        return {
            "signedURL": self.signed_url or (
                "/storage/v1/object/sign/artifacts/"
                + key + "?token=private-signed-token"
            )
        }


class FakeSession:
    def __init__(self, row):
        self.row = row
        self.queries = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, stmt, args):
        self.queries.append((str(stmt), args))
        return SimpleNamespace(fetchone=lambda: self.row)


def bounded_store(monkeypatch, *, body=_BODY, signed_url=None, row=None, transport=None):
    import ai_karen_engine.services.database.repositories.supabase_artifact_store as module

    if row is None:
        row = SimpleNamespace(
            name="author.txt", mime_type="text/plain", bytes=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
            storage_uri=f"supabase://artifacts/{_TENANT}/{_ARTIFACT}/author.txt",
        )
    session = FakeSession(row)
    storage = FakeStorage()
    storage.bucket = SignedBucket(signed_url)
    platform = SimpleNamespace(url="https://storage.example.test", storage=storage)
    store = SupabaseArtifactStore(
        session_factory=None, storage_client=platform
    )
    store._session = AsyncMock(return_value=session)
    real_client = module.httpx.AsyncClient
    if transport is None:
        def success(request):
            assert request.headers.get("range") == f"bytes=0-{len(body)-1}"
            assert request.url.host == "storage.example.test"
            assert request.url.path.endswith(
                f"/artifacts/{_TENANT}/{_ARTIFACT}/author.txt"
            )
            return httpx.Response(
                206, content=body,
                headers={
                    "Content-Range": f"bytes 0-{len(body)-1}/{len(body)}",
                    "Content-Length": str(len(body)),
                },
            )
        transport = httpx.MockTransport(success)
    monkeypatch.setattr(
        module.httpx, "AsyncClient",
        lambda *args, **kwargs: real_client(
            *args, transport=transport, **kwargs
        ),
    )
    return store, storage.bucket, session


@pytest.mark.asyncio
async def test_bounded_signed_range_returns_verified_owner_text(monkeypatch):
    store, bucket, session = bounded_store(monkeypatch)
    result = await store.read_owner_active_text_bounded(
        _ARTIFACT, _TENANT, _OWNER, max_bytes=65536
    )
    assert result.success
    assert result.data.text == _BODY.decode()
    assert result.data.sha256 == hashlib.sha256(_BODY).hexdigest()
    assert bucket.signatures == [(f"{_TENANT}/{_ARTIFACT}/author.txt", 60)]
    assert len(session.queries) == 1
    assert "FOR SHARE" in session.queries[0][0]
    assert session.queries[0][1]["owner_id"] == _OWNER


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ["full", "missing_range", "wrong_total", "oversend", "wrong_digest"])
async def test_bounded_signed_range_rejects_bad_storage_responses(monkeypatch, response):
    body = _BODY
    row = SimpleNamespace(
        name="author.txt", mime_type="text/plain", bytes=len(body),
        sha256=("0" * 64 if response == "wrong_digest"
                else hashlib.sha256(body).hexdigest()),
        storage_uri=f"supabase://artifacts/{_TENANT}/{_ARTIFACT}/author.txt",
    )
    def handler(request):
        if response == "full":
            return httpx.Response(200, content=body * 100000)
        if response == "missing_range":
            return httpx.Response(206, content=body)
        if response == "wrong_total":
            return httpx.Response(
                206, content=body,
                headers={"Content-Range": f"bytes 0-{len(body)-1}/{len(body)+1}"},
            )
        if response == "oversend":
            return httpx.Response(
                206, content=body + b"excess",
                headers={"Content-Range": f"bytes 0-{len(body)-1}/{len(body)}"},
            )
        return httpx.Response(
            206, content=body,
            headers={"Content-Range": f"bytes 0-{len(body)-1}/{len(body)}"},
        )
    store, bucket, _ = bounded_store(
        monkeypatch, body=body, row=row, transport=httpx.MockTransport(handler)
    )
    result = await store.read_owner_active_text_bounded(
        _ARTIFACT, _TENANT, _OWNER
    )
    assert not result.success
    assert result.data is None
    assert result.error == "bounded_artifact_read_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_url", [
    "https://other.example.test/storage/v1/object/sign/artifacts/"
    + _TENANT + "/" + _ARTIFACT + "/author.txt?token=secret",
    "/storage/v1/object/sign/other-bucket/"
    + _TENANT + "/" + _ARTIFACT + "/author.txt?token=secret",
    "/storage/v1/object/sign/artifacts/"
    + _TENANT + "/" + _ARTIFACT + "/author.txt",
    "http://storage.example.test/storage/v1/object/sign/artifacts/"
    + _TENANT + "/" + _ARTIFACT + "/author.txt?token=secret",
])
async def test_bounded_signed_range_blocks_untrusted_urls(monkeypatch, bad_url):
    def forbidden(request):
        raise AssertionError("HTTP must not run for untrusted URL")
    store, bucket, _ = bounded_store(
        monkeypatch, signed_url=bad_url,
        transport=httpx.MockTransport(forbidden),
    )
    result = await store.read_owner_active_text_bounded(
        _ARTIFACT, _TENANT, _OWNER
    )
    assert not result.success
    assert result.data is None
    assert len(bucket.signatures) == 1


@pytest.mark.asyncio
async def test_bounded_signed_range_rejects_missing_owner_without_storage(monkeypatch):
    store, bucket, session = bounded_store(monkeypatch)
    session.row = None
    result = await store.read_owner_active_text_bounded(
        _ARTIFACT, _TENANT, _OWNER
    )
    assert not result.success
    assert bucket.signatures == []


@pytest.mark.asyncio
async def test_bounded_signed_range_denies_invalid_byte_cap_without_session(monkeypatch):
    store, _, session = bounded_store(monkeypatch)
    for limit in (0, -1, 65537, True, "1000"):
        result = await store.read_owner_active_text_bounded(
            _ARTIFACT, _TENANT, _OWNER, max_bytes=limit
        )
        assert not result.success
    assert store._session.await_count == 0
