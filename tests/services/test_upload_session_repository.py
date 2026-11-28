"""Upload session repository boundary tests with deterministic SQL doubles."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_karen_engine.services.database.repositories.upload_session import (
    UploadSessionConflict,
    UploadSessionRepository,
)


TENANT = str(uuid4())
OWNER = str(uuid4())
SESSION = str(uuid4())
DIGEST = "a" * 64
KEY = "b" * 64


class Result:
    def __init__(self, record=None):
        self.record = record

    def first(self):
        return SimpleNamespace(_mapping=self.record) if self.record else None


class FakeSession:
    def __init__(self, record):
        self.record = record
        self.statements = []
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        self.statements.append((sql, params))
        if sql.strip().startswith("INSERT"):
            return Result()
        if sql.strip().startswith("UPDATE"):
            if self.record["state"] != params["expected_state"]:
                return Result()
            self.record["state"] = params["next_state"]
            if "artifact_id" in params:
                self.record["artifact_id"] = params["artifact_id"]
        return Result(self.record)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def record():
    return {
        "session_id": SESSION,
        "tenant_id": TENANT,
        "owner_user_id": OWNER,
        "destination_id": "explorer",
        "recipe": "store_only",
        "state": "created",
        "manifest_sha256": DIGEST,
        "expected_bytes": 42,
        "received_bytes": 0,
        "artifact_id": None,
        "expected_sha256": None,
        "lease_owner": None,
        "lease_expires_at": None,
        "storage_key": None,
    }


@pytest.mark.asyncio
async def test_create_or_get_reuses_matching_manifest_and_scopes_queries():
    db = FakeSession(record())
    repo = UploadSessionRepository(lambda: db)
    result = await repo.create_or_get(
        tenant_id=TENANT, owner_user_id=OWNER,
        destination_id="explorer", recipe="store_only",
        idempotency_key_hash=KEY, manifest_sha256=DIGEST,
        expected_bytes=42, expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    assert result.session_id == SESSION
    assert db.committed
    assert "READ COMMITTED" in db.statements[0][0]
    assert "pg_advisory_xact_lock" in db.statements[1][0]
    assert db.statements[1][1]["quota_lock"] == f"artifact-upload-admission:{TENANT}:{OWNER}"
    assert all(params["tenant_id"] == TENANT for _, params in db.statements[2:])
    assert all(params["owner_user_id"] == OWNER for _, params in db.statements[2:])
    assert "ON CONFLICT" in db.statements[2][0]
    assert "count(*) < :admission_sessions" in db.statements[2][0]
    assert "sum(expected_bytes)" in db.statements[2][0]
    assert db.statements[2][0].count("CAST(:expected_bytes AS BIGINT)") == 2
    assert "CAST(:admission_bytes AS BIGINT)" in db.statements[2][0]
    assert "interval '24 hours'" in db.statements[2][0]
    assert "FOR UPDATE" in db.statements[3][0]


@pytest.mark.asyncio
async def test_conflicting_idempotency_manifest_fails_closed():
    db = FakeSession(record())
    repo = UploadSessionRepository(lambda: db)
    with pytest.raises(UploadSessionConflict):
        await repo.create_or_get(
            tenant_id=TENANT, owner_user_id=OWNER,
            destination_id="other", recipe="store_only",
            idempotency_key_hash=KEY, manifest_sha256=DIGEST,
            expected_bytes=42, expires_at=datetime.utcnow() + timedelta(hours=1),
        )
    assert not db.committed


@pytest.mark.asyncio
async def test_transition_is_compare_and_swap_and_owner_scoped():
    db = FakeSession(record())
    repo = UploadSessionRepository(lambda: db)
    changed = await repo.transition(
        tenant_id=TENANT, owner_user_id=OWNER, session_id=SESSION,
        expected_state="created", next_state="receiving",
    )
    assert changed is not None and changed.state == "receiving"
    assert db.committed
    lock_sql, update_sql = (statement for statement, _ in db.statements)
    assert "FOR UPDATE" in lock_sql
    assert "owner_user_id = :owner_user_id" in lock_sql
    assert "tenant_id = :tenant_id" in lock_sql
    assert "owner_user_id = :owner_user_id" in update_sql
    assert "expires_at > clock_timestamp()" in update_sql


@pytest.mark.asyncio
async def test_illegal_or_unproven_commit_is_denied():
    repo = UploadSessionRepository(lambda: FakeSession(record()))
    with pytest.raises(ValueError):
        await repo.transition(
            tenant_id=TENANT, owner_user_id=OWNER, session_id=SESSION,
            expected_state="created", next_state="committed",
        )
    with pytest.raises(ValueError):
        await repo.transition(
            tenant_id=TENANT, owner_user_id=OWNER, session_id=SESSION,
            expected_state="committing", next_state="committed",
        )


@pytest.mark.asyncio
async def test_generic_commit_cannot_bypass_verified_readback():
    db = FakeSession({**record(), "state": "committing"})
    repo = UploadSessionRepository(lambda: db)
    with pytest.raises(ValueError, match="Illegal upload state"):
        await repo.transition(
            tenant_id=TENANT, owner_user_id=OWNER, session_id=SESSION,
            expected_state="committing", next_state="committed",
            artifact_id=SESSION, lease_token=SESSION,
        )
    assert db.statements == []


@pytest.mark.asyncio
async def test_cannot_bind_artifact_before_verified_commit():
    repo = UploadSessionRepository(lambda: FakeSession(record()))
    with pytest.raises(ValueError, match="only through verified readback"):
        await repo.transition(
            tenant_id=TENANT, owner_user_id=OWNER, session_id=SESSION,
            expected_state="created", next_state="receiving",
            artifact_id=str(uuid4()),
        )


@pytest.mark.asyncio
async def test_rejects_non_uuid_tenant_before_database_access():
    repo = UploadSessionRepository(lambda: FakeSession(record()))
    with pytest.raises(ValueError, match="tenant_id must be a UUID"):
        await repo.create_or_get(
            tenant_id="tenant-a", owner_user_id=OWNER,
            destination_id="explorer", recipe="store_only",
            idempotency_key_hash=KEY, manifest_sha256=DIGEST,
            expected_bytes=42, expires_at=datetime.utcnow() + timedelta(hours=1),
        )


@pytest.mark.asyncio
async def test_create_or_get_requires_unexpired_existing_session():
    db = FakeSession(record())
    repo = UploadSessionRepository(lambda: db)
    await repo.create_or_get(
        tenant_id=TENANT, owner_user_id=OWNER,
        destination_id="explorer", recipe="store_only",
        idempotency_key_hash=KEY, manifest_sha256=DIGEST,
        expected_bytes=42, expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    select_sql = db.statements[3][0]
    assert "expires_at > now()" in select_sql
    assert "FOR UPDATE" in select_sql



@pytest.mark.asyncio
async def test_creation_pins_content_digest_to_idempotency_manifest():
    db = FakeSession({**record(), "expected_sha256": DIGEST})
    repo = UploadSessionRepository(lambda: db)
    params = dict(
        tenant_id=TENANT, owner_user_id=OWNER,
        destination_id="explorer", recipe="store_only",
        idempotency_key_hash=KEY, manifest_sha256=DIGEST,
        expected_bytes=42, expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    result = await repo.create_or_get(**params, expected_sha256=DIGEST)
    assert result.expected_sha256 == DIGEST
    assert db.statements[2][1]["expected_sha256"] == DIGEST
    for changed in (None, "c" * 64):
        with pytest.raises(UploadSessionConflict):
            await repo.create_or_get(**params, expected_sha256=changed)
    with pytest.raises(ValueError, match="content SHA-256"):
        await repo.create_or_get(**params, expected_sha256="not-a-digest")



@pytest.mark.asyncio
@pytest.mark.parametrize("expected_state,next_state", [
    ("receiving", "staged"), ("staged", "committing"),
    ("reconcile_required", "committing"), ("reconcile_required", "committed"),
])
async def test_generic_transition_cannot_bypass_staging_claim_or_recovery(
    expected_state, next_state,
):
    db = FakeSession(record())
    repo = UploadSessionRepository(lambda: db)
    with pytest.raises(ValueError, match="Illegal upload state"):
        await repo.transition(
            tenant_id=TENANT, owner_user_id=OWNER, session_id=SESSION,
            expected_state=expected_state, next_state=next_state,
        )
    assert db.statements == []


@pytest.mark.asyncio
async def test_commit_requires_lease_before_database_access():
    db = FakeSession(record())
    repo = UploadSessionRepository(lambda: db)
    with pytest.raises(ValueError, match="Active commit lease"):
        await repo.transition(
            tenant_id=TENANT, owner_user_id=OWNER, session_id=SESSION,
            expected_state="committing", next_state="reconcile_required",
        )
    assert db.statements == []



@pytest.mark.asyncio
async def test_commit_rejects_unreserved_artifact_before_database_access():
    db = FakeSession(record())
    repo = UploadSessionRepository(lambda: db)
    with pytest.raises(ValueError, match="Illegal upload state"):
        await repo.transition(
            tenant_id=TENANT, owner_user_id=OWNER, session_id=SESSION,
            expected_state="committing", next_state="committed",
            artifact_id=str(uuid4()), lease_token=SESSION,
        )
    assert db.statements == []


@pytest.mark.asyncio
async def test_readback_failure_never_rewrites_uncertain_session():
    from unittest.mock import AsyncMock

    db = FakeSession({
        **record(), "state": "reconcile_required",
        "expected_sha256": DIGEST, "received_bytes": 42,
        "storage_key": f"{TENANT}/{SESSION}/content",
    })
    repo = UploadSessionRepository(lambda: db)
    store = SimpleNamespace(
        read_owner_active_text_bounded=AsyncMock(return_value=SimpleNamespace(
            success=False, data=None,
        )),
    )
    assert await repo.reconcile_verified_text(
        tenant_id=TENANT, owner_user_id=OWNER, session_id=SESSION,
        artifact_store=store,
    ) is None
    store.read_owner_active_text_bounded.assert_awaited_once_with(
        SESSION, TENANT, OWNER, max_bytes=42, expected_sha256=DIGEST,
    )
    assert len(db.statements) == 1
    assert not db.committed

@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["match", "missing", "wrong_owner", "wrong_digest", "wrong_bytes"])
async def test_committed_readback_is_scoped_pinned_and_read_only(case):
    import hashlib
    from unittest.mock import AsyncMock
    from ai_karen_engine.services.database.repositories.artifact_store import VerifiedArtifactText

    body = "verified receipt"
    digest = hashlib.sha256(body.encode()).hexdigest()
    db = FakeSession(None if case == "missing" else {
        **record(), "state": "committed", "artifact_id": SESSION,
        "expected_bytes": len(body.encode()), "received_bytes": len(body.encode()),
        "expected_sha256": digest, "storage_key": f"{TENANT}/{SESSION}/content",
    })
    repo = UploadSessionRepository(lambda: db)
    proof = VerifiedArtifactText(
        artifact_id=SESSION, tenant_id=TENANT,
        user_id=str(uuid4()) if case == "wrong_owner" else OWNER,
        filename="receipt.txt", mime_type="text/plain",
        sha256=DIGEST if case == "wrong_digest" else digest,
        text="x" * len(body) if case == "wrong_bytes" else body,
    )
    store = SimpleNamespace(read_owner_active_text_bounded=AsyncMock(
        return_value=SimpleNamespace(success=True, data=proof),
    ))
    result = await repo.read_committed_verified_text(
        tenant_id=TENANT, owner_user_id=OWNER, session_id=SESSION, artifact_store=store,
    )
    assert result == (proof if case == "match" else None)
    assert len(db.statements) == 1
    sql, params = db.statements[0]
    assert sql.strip().startswith("SELECT")
    assert "upload.state = 'committed'" in sql
    assert "upload.artifact_id = :reserved_artifact_id" in sql
    assert "artifact.deleted_at IS NULL" in sql
    assert "artifact.sha256 = upload.expected_sha256" in sql
    assert "artifact.owner_user_id = :owner_user_id" in sql
    assert params == {"tenant_id": TENANT, "owner_user_id": OWNER,
                      "session_id": SESSION, "reserved_artifact_id": SESSION,
                      "storage_key": f"{TENANT}/{SESSION}/content"}
    assert not db.committed and not db.rolled_back
    if case == "missing":
        store.read_owner_active_text_bounded.assert_not_awaited()
    else:
        store.read_owner_active_text_bounded.assert_awaited_once_with(
            SESSION, TENANT, OWNER, max_bytes=len(body.encode()), expected_sha256=digest,
        )

@pytest.mark.asyncio
async def test_admission_budget_uses_validated_runtime_limits(monkeypatch):
    monkeypatch.setenv("KAREN_UPLOAD_ADMISSION_DAILY_SESSIONS", "3")
    monkeypatch.setenv("KAREN_UPLOAD_ADMISSION_DAILY_BYTES", "100")
    db = FakeSession(record())
    await UploadSessionRepository(lambda: db).create_or_get(
        tenant_id=TENANT, owner_user_id=OWNER,
        destination_id="explorer", recipe="store_only",
        idempotency_key_hash=KEY, manifest_sha256=DIGEST,
        expected_bytes=42, expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    assert db.statements[2][1]["admission_sessions"] == 3
    assert db.statements[2][1]["admission_bytes"] == 100


@pytest.mark.asyncio
@pytest.mark.parametrize("setting,value", [
    ("KAREN_UPLOAD_ADMISSION_DAILY_SESSIONS", "0"),
    ("KAREN_UPLOAD_ADMISSION_DAILY_BYTES", "invalid"),
])
async def test_invalid_admission_budget_fails_before_sql(monkeypatch, setting, value):
    monkeypatch.setenv(setting, value)
    db = FakeSession(record())
    with pytest.raises(ValueError):
        await UploadSessionRepository(lambda: db).create_or_get(
            tenant_id=TENANT, owner_user_id=OWNER,
            destination_id="explorer", recipe="store_only",
            idempotency_key_hash=KEY, manifest_sha256=DIGEST,
            expected_bytes=42, expires_at=datetime.utcnow() + timedelta(hours=1),
        )
    assert db.statements == []
