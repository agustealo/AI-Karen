"""CK-GEN-01B: owner and active-state verified inert artifact byte readback."""

import hashlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_karen_engine.services.database.repositories.supabase_artifact_store import (
    SupabaseArtifactStore,
)
from ai_karen_engine.services.database.repositories.artifact_store import (
    VerifiedArtifactText,
)


TENANT = str(uuid.UUID("10000000-0000-4000-8000-000000000001"))
OWNER = str(uuid.UUID("10000000-0000-4000-8000-000000000002"))
OTHER = str(uuid.UUID("10000000-0000-4000-8000-000000000003"))
FILE = str(uuid.UUID("10000000-0000-4000-8000-000000000004"))
SOURCE = b"print('source text only')\n"


def _store(*, returned=SOURCE, row_changes=None):
    row = {
        "file_id": FILE,
        "tenant_id": TENANT,
        "owner_user_id": OWNER,
        "name": "demo.py",
        "mime_type": "text/x-python",
        "bytes": len(SOURCE),
        "storage_uri": f"supabase://artifacts/{TENANT}/{FILE}/demo.py",
        "sha256": hashlib.sha256(SOURCE).hexdigest(),
    }
    row.update(row_changes or {})
    database = SimpleNamespace(fetchone=lambda: SimpleNamespace(**row))
    session = MagicMock()
    session.execute = AsyncMock(return_value=database)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    bucket = MagicMock()
    bucket.download.return_value = returned
    storage = SimpleNamespace(storage=SimpleNamespace(from_=lambda _name: bucket))
    store = SupabaseArtifactStore(AsyncMock(return_value=session), storage)
    return store, session, bucket


@pytest.mark.asyncio
async def test_owner_active_verified_code_is_inert_and_digest_bound():
    store, session, bucket = _store()
    outcome = await store.read_owner_active_code(FILE, TENANT, OWNER)
    assert outcome.success
    assert isinstance(outcome.data, VerifiedArtifactText)
    assert outcome.data.text == SOURCE.decode("utf-8")
    assert outcome.data.sha256 == hashlib.sha256(SOURCE).hexdigest()
    assert outcome.data.filename == "demo.py"
    sql = str(session.execute.await_args.args[0])
    assert "owner_user_id = :user_id" in sql
    assert "tenant_id = :tenant_id" in sql
    assert "deleted_at IS NULL" in sql
    assert "FOR SHARE" in sql
    assert session.execute.await_args.args[1] == {
        "file_id": FILE, "tenant_id": TENANT, "user_id": OWNER,
    }
    bucket.download.assert_called_once_with(f"{TENANT}/{FILE}/demo.py")


@pytest.mark.asyncio
async def test_invalid_principals_never_query_or_download():
    store, session, bucket = _store()
    for scope in ((FILE, "invalid", OWNER), (FILE, TENANT, "invalid"), ("not-a-uuid", TENANT, OWNER)):
        outcome = await store.read_owner_active_code(*scope)
        assert not outcome.success
        assert outcome.data is None
    session.execute.assert_not_awaited()
    bucket.download.assert_not_called()


@pytest.mark.asyncio
async def test_owner_denial_or_archived_record_never_reads_storage():
    store, session, bucket = _store()
    session.execute.return_value.fetchone = lambda: None
    for principal in (OWNER, OTHER):
        outcome = await store.read_owner_active_code(FILE, TENANT, principal)
        assert not outcome.success
        assert outcome.data is None
    bucket.download.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"mime_type": "text/html"},
    {"name": "../demo.py"},
    {"name": "demo.svg"},
    {"bytes": 0},
    {"bytes": 32769},
    {"sha256": "not-a-digest"},
    {"storage_uri": "supabase://artifacts/foreign/secret"},
])
async def test_untrusted_artifact_metadata_denied_before_download(changes):
    store, _, bucket = _store(row_changes=changes)
    outcome = await store.read_owner_active_code(FILE, TENANT, OWNER)
    assert not outcome.success
    assert outcome.data is None
    bucket.download.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_bytes", [
    b"tampered bytes",
    b"\xff" * len(SOURCE),
    b"",
    SOURCE + b"extra",
])
async def test_digest_size_or_encoding_drift_never_discloses_content(bad_bytes):
    store, _, _ = _store(returned=bad_bytes)
    outcome = await store.read_owner_active_code(FILE, TENANT, OWNER)
    assert not outcome.success
    assert outcome.data is None


@pytest.mark.asyncio
async def test_valid_digest_but_invalid_control_bytes_fail_closed():
    data = b"bad\x00text"
    store, _, _ = _store(
        returned=data,
        row_changes={
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    )
    outcome = await store.read_owner_active_code(FILE, TENANT, OWNER)
    assert not outcome.success
    assert outcome.data is None


@pytest.mark.asyncio
async def test_storage_unavailability_yields_no_text_or_metadata():
    store, _, bucket = _store()
    bucket.download.side_effect = RuntimeError("storage offline")
    outcome = await store.read_owner_active_code(FILE, TENANT, OWNER)
    assert not outcome.success
    assert outcome.data is None
    assert outcome.error == "artifact_code_unavailable"
