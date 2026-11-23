"""Prove artifact storage uses the initialized canonical platform bucket."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
import hashlib
import logging
import time

import httpx

import pytest

from ai_karen_engine.services.database.repositories.artifact_store import (
    ArtifactUploadRequest,
)
from ai_karen_engine.services.database.repositories.supabase_artifact_store import (
    SupabaseArtifactStore,
)


class UnconsumedStream(httpx.AsyncByteStream):
    """Feed HTTPX real async response bytes, without eager stream consumption."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self.reads = 0

    async def __aiter__(self):
        self.reads += 1
        yield self._data


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
        self.exits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.exits += 1
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
            storage_uri=f"supabase://artifacts/{_TENANT}/{_ARTIFACT}/content",
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
                f"/artifacts/{_TENANT}/{_ARTIFACT}/content"
            )
            return httpx.Response(
                206, stream=UnconsumedStream(body),
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
async def test_bounded_signed_range_preserves_multiline_utf8(monkeypatch):
    body = "First line of an author's note.\n\tSecond line.\r\nThird line.".encode("utf-8")
    store, _, _ = bounded_store(monkeypatch, body=body)
    result = await store.read_owner_active_text_bounded(
        _ARTIFACT, _TENANT, _OWNER, max_bytes=65536
    )
    assert result.success
    assert result.data.text == body.decode("utf-8")


@pytest.mark.asyncio
async def test_bounded_signed_range_returns_verified_owner_text(monkeypatch):
    store, bucket, session = bounded_store(monkeypatch)
    result = await store.read_owner_active_text_bounded(
        _ARTIFACT, _TENANT, _OWNER, max_bytes=65536
    )
    assert result.success
    assert result.data.text == _BODY.decode()
    assert result.data.sha256 == hashlib.sha256(_BODY).hexdigest()
    assert bucket.signatures == [(f"{_TENANT}/{_ARTIFACT}/content", 60)]
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
        storage_uri=f"supabase://artifacts/{_TENANT}/{_ARTIFACT}/content",
    )
    streams = []

    def handler(request):
        response_body = body + b"excess" if response == "oversend" else body
        stream = UnconsumedStream(response_body)
        streams.append(stream)
        if response == "full":
            return httpx.Response(200, stream=stream)
        if response == "missing_range":
            return httpx.Response(206, stream=stream)
        if response == "wrong_total":
            return httpx.Response(
                206, stream=stream,
                headers={"Content-Range": f"bytes 0-{len(body)-1}/{len(body)+1}"},
            )
        return httpx.Response(
            206, stream=stream,
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
    # Header failures must reject before any content consumption.
    # Oversized responses and wrong digests must exercise a real raw stream.
    assert len(streams) == 1
    expected_reads = 1 if response in {"oversend", "wrong_digest"} else 0
    assert streams[0].reads == expected_reads


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_url", [
    "/storage/v1/object/sign/artifacts/"
    + _TENANT + "/" + _ARTIFACT + "/author.txt?token=secret",
    "https://other.example.test/storage/v1/object/sign/artifacts/"
    + _TENANT + "/" + _ARTIFACT + "/content?token=secret",
    "/storage/v1/object/sign/other-bucket/"
    + _TENANT + "/" + _ARTIFACT + "/content?token=secret",
    "/storage/v1/object/sign/artifacts/"
    + _TENANT + "/" + _ARTIFACT + "/content",
    "http://storage.example.test/storage/v1/object/sign/artifacts/"
    + _TENANT + "/" + _ARTIFACT + "/content?token=secret",
    "/storage/v1/object/sign/artifacts/"
    + _TENANT + "/" + _ARTIFACT + "/content?%74oken=eyJabc%2EeyJdef%2Eghi",
    "/storage/v1/object/%73ign/artifacts/"
    + _TENANT + "/" + _ARTIFACT + "/content?token=secret",
    "/storage/v1/object/sign/artifacts/"
    + _TENANT + "/" + _ARTIFACT + "/%63ontent?token=secret",
    "/storage/v1/object/sign/artifacts/"
    + _TENANT + "/" + _ARTIFACT + "/conten%74?token=secret",
])
async def test_bounded_signed_range_blocks_untrusted_urls(monkeypatch, bad_url):
    attempted_requests = []

    def forbidden(request):
        attempted_requests.append(request)
        return httpx.Response(500, content=b"forbidden-request-attempted")

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
    # A fail-closed repository exception must not conceal that a network
    # request was attempted. Count transport calls, not just result status.
    assert attempted_requests == []


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


@pytest.mark.asyncio
async def test_bounded_signed_range_stops_consuming_oversized_stream(monkeypatch):
    """A hostile server may emit unlimited bytes despite correct 206 headers."""
    class CountingStream(httpx.AsyncByteStream):
        def __init__(self):
            self.chunks_sent = 0

        async def __aiter__(self):
            for _ in range(4096):
                self.chunks_sent += 1
                yield b"Z" * 4096

    hostile = CountingStream()

    def response(request):
        return httpx.Response(
            206,
            headers={"Content-Range": f"bytes 0-{len(_BODY)-1}/{len(_BODY)}"},
            stream=hostile,
        )

    store, bucket, _ = bounded_store(
        monkeypatch, transport=httpx.MockTransport(response)
    )
    result = await store.read_owner_active_text_bounded(
        _ARTIFACT, _TENANT, _OWNER
    )
    assert not result.success
    assert result.data is None
    # Incremental consumption must stop on the first over-budget chunk.
    assert hostile.chunks_sent == 1
    assert len(bucket.signatures) == 1


@pytest.mark.asyncio
async def test_bounded_signed_range_fails_closed_for_insecure_origin(monkeypatch):
    store, bucket, _ = bounded_store(monkeypatch)
    store._storage.url = "http://remote-storage.example.test"
    result = await store.read_owner_active_text_bounded(
        _ARTIFACT, _TENANT, _OWNER
    )
    assert not result.success
    assert result.data is None
    assert bucket.signatures == []


@pytest.mark.asyncio
async def test_bounded_signed_storage_httpx_logs_never_expose_token(
    monkeypatch, caplog
):
    """The actual HTTPX INFO event is safe even in Karen's text log format."""
    from ai_karen_engine.core.logging.formatters import RuntimeTextFormatter

    secret = "private-signed-token-DoNotLog123"
    def handle(request):
        assert request.url.params["token"] == secret
        return httpx.Response(
            206, stream=UnconsumedStream(_BODY),
            headers={
                "Content-Range": f"bytes 0-{len(_BODY)-1}/{len(_BODY)}"
            },
        )

    store, _, _ = bounded_store(
        monkeypatch,
        signed_url=(
            f"/storage/v1/object/sign/artifacts/{_TENANT}/"
            f"{_ARTIFACT}/content?token={secret}"
        ),
        transport=httpx.MockTransport(handle),
    )
    with caplog.at_level(logging.INFO, logger="httpx"):
        result = await store.read_owner_active_text_bounded(
            _ARTIFACT, _TENANT, _OWNER
        )
        # Ensure the filter does not suppress unrelated HTTPX log events.
        logging.getLogger("httpx").info("HTTP Request: ordinary public URL")
    assert result.success is True
    formatted = [
        RuntimeTextFormatter().format(record)
        for record in caplog.records if record.name == "httpx"
    ]
    assert formatted
    signed_response_records = [
        record for record in caplog.records
        if record.name == "httpx"
        and "HTTP Request: GET " in record.getMessage()
        and "/storage/v1/object/sign/artifacts/" in record.getMessage()
        and "206 Partial Content" in record.getMessage()
    ]
    # A synthetic unrelated HTTPX event cannot substitute for the real
    # signed-object HTTP 206 response log record.
    assert len(signed_response_records) == 1
    signed_record = signed_response_records[0]
    assert "token=[REDACTED]" in signed_record.getMessage()
    assert secret not in signed_record.getMessage()
    assert secret not in RuntimeTextFormatter().format(signed_record)
    assert all(secret not in line for line in formatted)
    assert any("ordinary public URL" in line for line in formatted)
    assert all(secret not in record.getMessage() for record in caplog.records)


def test_signed_url_redaction_covers_short_and_encoded_tokens():
    from ai_karen_engine.core.logging.redaction import redact_text

    for token in ("s", "private-signed-token", "foo%2Fbar%3D"):
        raw = f"https://storage.example.test/object?token={token}"
        result = redact_text(raw)
        assert f"token={token}" not in result
        assert "token=[REDACTED]" in result



def test_artifact_storage_deadline_config_validation(monkeypatch):
    from ai_karen_engine.config.artifact_storage import ArtifactStorageConfig

    monkeypatch.delenv("KAREN_ARTIFACT_SIGNED_RANGE_DEADLINE_SECONDS", raising=False)
    assert ArtifactStorageConfig.from_environment().signed_range_total_timeout_seconds == 20.0

    for raw in ("0", "-1", "121", "nan", "inf", "-inf", "false", "", "1e999"):
        monkeypatch.setenv("KAREN_ARTIFACT_SIGNED_RANGE_DEADLINE_SECONDS", raw)
        with pytest.raises(ValueError, match="Invalid artifact signed-range deadline"):
            ArtifactStorageConfig.from_environment()

    for raw in ("0.02", "1", "120"):
        monkeypatch.setenv("KAREN_ARTIFACT_SIGNED_RANGE_DEADLINE_SECONDS", raw)
        assert ArtifactStorageConfig.from_environment().signed_range_total_timeout_seconds == float(raw)


@pytest.mark.asyncio
async def test_bounded_signed_range_total_deadline_denies_slow_trickle(monkeypatch):
    """An endpoint may trickle bytes forever without hitting idle timeouts."""

    class SlowTrickle(httpx.AsyncByteStream):
        def __init__(self):
            self.chunks = 0

        async def __aiter__(self):
            for _ in range(len(_BODY)):
                await asyncio.sleep(0.025)
                self.chunks += 1
                yield b"x"

    trickle = SlowTrickle()

    def responder(request):
        return httpx.Response(
            206,
            stream=trickle,
            headers={
                "Content-Range": f"bytes 0-{len(_BODY)-1}/{len(_BODY)}",
                "Content-Length": str(len(_BODY)),
            },
        )

    store, bucket, session = bounded_store(
        monkeypatch, transport=httpx.MockTransport(responder)
    )
    monkeypatch.setenv("KAREN_ARTIFACT_SIGNED_RANGE_DEADLINE_SECONDS", "0.05")
    started = time.monotonic()
    denied = await store.read_owner_active_text_bounded(
        _ARTIFACT, _TENANT, _OWNER
    )
    elapsed = time.monotonic() - started

    assert not denied.success and denied.data is None
    assert denied.error == "bounded_artifact_read_unavailable"
    assert elapsed < 0.75
    assert trickle.chunks < len(_BODY)
    assert len(bucket.signatures) == 1
    assert session.exits == 1


@pytest.mark.asyncio
async def test_bounded_signed_range_total_deadline_denies_slow_signer(monkeypatch):
    """A slow synchronous SDK call runs in a worker but cannot hold the lock forever."""
    store, bucket, session = bounded_store(monkeypatch)

    def slow_sign(path, expiry):
        time.sleep(0.2)
        return {"signedURL": (
            f"/storage/v1/object/sign/artifacts/{path}?token=private-signed-token"
        )}

    monkeypatch.setattr(bucket, "create_signed_url", slow_sign)
    monkeypatch.setenv("KAREN_ARTIFACT_SIGNED_RANGE_DEADLINE_SECONDS", "0.05")
    started = time.monotonic()
    denied = await store.read_owner_active_text_bounded(
        _ARTIFACT, _TENANT, _OWNER
    )
    elapsed = time.monotonic() - started

    assert not denied.success and denied.data is None
    assert denied.error == "bounded_artifact_read_unavailable"
    assert elapsed < 0.75
    assert session.exits == 1


@pytest.mark.asyncio
async def test_bounded_signed_range_total_deadline_allows_fast_real_range(monkeypatch):
    store, _, session = bounded_store(monkeypatch)
    monkeypatch.setenv("KAREN_ARTIFACT_SIGNED_RANGE_DEADLINE_SECONDS", "1.0")
    passed = await store.read_owner_active_text_bounded(
        _ARTIFACT, _TENANT, _OWNER
    )
    assert passed.success and passed.data is not None
    assert passed.data.sha256 == hashlib.sha256(_BODY).hexdigest()
    assert session.exits == 1


@pytest.mark.asyncio
async def test_bounded_read_rechecks_live_bytes_when_object_drifts_without_sql_write(
    monkeypatch,
):
    """Byte replacement behind an unchanged canonical row cannot be approved."""
    body = _BODY
    object_bytes = [body]
    reads = []

    # Canonical PostgreSQL metadata stays unchanged across all three calls.
    immutable_row = SimpleNamespace(
        name="author.txt",
        mime_type="text/plain",
        bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        storage_uri=f"supabase://artifacts/{_TENANT}/{_ARTIFACT}/content",
    )

    def live_object(request):
        reads.append(str(request.url))
        assert request.url.path == (
            f"/storage/v1/object/sign/artifacts/{_TENANT}/{_ARTIFACT}/content"
        )
        assert request.headers["range"] == f"bytes=0-{len(body)-1}"
        return httpx.Response(
            206,
            stream=UnconsumedStream(object_bytes[0]),
            headers={
                "Content-Range": f"bytes 0-{len(body)-1}/{len(body)}",
                "Content-Length": str(len(body)),
            },
        )

    store, bucket, session = bounded_store(
        monkeypatch, row=immutable_row,
        transport=httpx.MockTransport(live_object),
    )
    original = await store.read_owner_active_text_bounded(
        _ARTIFACT, _TENANT, _OWNER,
    )
    assert original.success is True and original.data.text == body.decode()
    original_digest = immutable_row.sha256

    # Supabase object changes out-of-band, with an identical byte length.
    # No SQL UPDATE, archive, or trigger runs.
    object_bytes[0] = body[:-1] + (b"!" if body[-1:] != b"!" else b"?")
    assert len(object_bytes[0]) == len(body)
    tampered = await store.read_owner_active_text_bounded(
        _ARTIFACT, _TENANT, _OWNER,
    )
    assert tampered.success is False
    assert tampered.data is None
    assert tampered.error == "bounded_artifact_read_unavailable"
    assert immutable_row.sha256 == original_digest
    assert immutable_row.bytes == len(body)

    # If object bytes are restored, the bounded reader can verify them
    # again. Receipt validity and irreversible revocation are separate
    # SQL authorities, not outcomes inferred from this storage test.
    object_bytes[0] = body
    restored = await store.read_owner_active_text_bounded(
        _ARTIFACT, _TENANT, _OWNER,
    )
    assert restored.success is True
    assert restored.data.sha256 == original_digest
    assert len(reads) == len(bucket.signatures) == len(session.queries) == 3


@pytest.mark.asyncio
async def test_bounded_read_rejects_noncanonical_storage_locator_before_signing(
    monkeypatch,
):
    """Legacy filename keys and malicious aliases are never chosen."""
    row = SimpleNamespace(
        name="author.txt",
        mime_type="text/plain",
        bytes=len(_BODY),
        sha256=hashlib.sha256(_BODY).hexdigest(),
        storage_uri=f"supabase://artifacts/{_TENANT}/{_ARTIFACT}/author.txt",
    )
    store, bucket, _ = bounded_store(monkeypatch, row=row)
    denied = await store.read_owner_active_text_bounded(
        _ARTIFACT, _TENANT, _OWNER,
    )
    assert denied.success is False
    assert denied.data is None
    assert bucket.signatures == []


def test_canonical_object_storage_key_is_identical_for_upload_and_read():
    """One stable key owner, independent from a user-controlled filename."""
    key = SupabaseArtifactStore._canonical_object_key(_TENANT, _ARTIFACT)
    assert key == f"{_TENANT}/{_ARTIFACT}/content"
    assert "author.txt" not in key


@pytest.mark.asyncio
async def test_upload_and_bounded_reader_share_actual_canonical_storage_key():
    """A real upload writes /content, never a user-controlled name key."""
    class InsertSession:
        def __init__(self):
            self.sql = []
            self.commits = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, stmt, args):
            self.sql.append((str(stmt), args))

        async def commit(self):
            self.commits += 1

    session = InsertSession()
    storage = FakeStorage()
    store = SupabaseArtifactStore(
        session_factory=None,
        storage_client=SimpleNamespace(storage=storage),
    )
    store._session = AsyncMock(return_value=session)
    uploaded = await store.upload(ArtifactUploadRequest(
        tenant_id=_TENANT, user_id=_OWNER,
        filename="author.txt", content_type="text/plain",
        data=_BODY,
    ))
    assert uploaded.success is True and uploaded.data is not None
    saved = uploaded.data
    expected_key = f"{_TENANT}/{saved.id}/content"
    assert saved.storage_key == expected_key
    assert storage.bucket.files == {expected_key: _BODY}
    assert session.commits == 1
    assert len(session.sql) == 1
    persisted = session.sql[0][1]
    assert persisted["storage_uri"] == f"supabase://artifacts/{expected_key}"
    assert persisted["sha256"] == hashlib.sha256(_BODY).hexdigest()
    assert persisted["name"] == "author.txt"


@pytest.mark.asyncio
async def test_active_code_reader_uses_same_canonical_storage_key():
    """No separate filename-key storage model survives in legacy code reads."""
    row = SimpleNamespace(
        name="author.txt", mime_type="text/plain", bytes=len(_BODY),
        sha256=hashlib.sha256(_BODY).hexdigest(),
        storage_uri=f"supabase://artifacts/{_TENANT}/{_ARTIFACT}/content",
    )
    session = FakeSession(row)
    storage = FakeStorage()
    canonical = f"{_TENANT}/{_ARTIFACT}/content"
    storage.bucket.files[canonical] = _BODY
    store = SupabaseArtifactStore(
        session_factory=None,
        storage_client=SimpleNamespace(storage=storage),
    )
    store._session = AsyncMock(return_value=session)
    verified = await store.read_owner_active_code(_ARTIFACT, _TENANT, _OWNER)
    assert verified.success and verified.data is not None
    assert verified.data.text == _BODY.decode("utf-8")
    assert storage.bucket.files[canonical] == _BODY

    # A record pointing at the old display-filename path is not trusted.
    session.row = SimpleNamespace(
        **{**vars(row),
           "storage_uri": f"supabase://artifacts/{_TENANT}/{_ARTIFACT}/author.txt"}
    )
    rejected = await store.read_owner_active_code(_ARTIFACT, _TENANT, _OWNER)
    assert rejected.success is False and rejected.data is None
