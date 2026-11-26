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

    async def execute(self, statement, params):
        sql = str(statement)
        self.statements.append((sql, params))
        if sql.strip().startswith("INSERT"):
            return Result()
        if sql.strip().startswith("UPDATE"):
            if self.record["state"] != params["expected_state"]:
                return Result()
            self.record["state"] = params["next_state"]
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
    assert all(params["tenant_id"] == TENANT for _, params in db.statements)
    assert all(params["owner_user_id"] == OWNER for _, params in db.statements)
    assert "ON CONFLICT" in db.statements[0][0]
    assert "FOR UPDATE" in db.statements[1][0]


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
    assert "owner_user_id = :owner_user_id" in db.statements[0][0]
    assert "expires_at > now()" in db.statements[0][0]


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
async def test_committed_transition_requires_active_owner_matched_artifact():
    db = FakeSession({**record(), "state": "committing"})
    repo = UploadSessionRepository(lambda: db)
    artifact_id = str(uuid4())
    await repo.transition(
        tenant_id=TENANT, owner_user_id=OWNER, session_id=SESSION,
        expected_state="committing", next_state="committed",
        artifact_id=artifact_id, lease_token=SESSION,
    )
    statement = db.statements[0][0]
    assert "received_bytes = expected_bytes" in statement
    assert "FROM public.files AS artifact" in statement
    assert "artifact.tenant_id = :tenant_id" in statement
    assert "artifact.owner_user_id = :owner_user_id" in statement
    assert "artifact.deleted_at IS NULL" in statement
    assert "artifact.bytes = expected_bytes" in statement
    assert "artifact.sha256 = expected_sha256" in statement
    assert "expected_sha256 IS NOT NULL" in statement
    assert "expected_sha256 IS NULL" not in statement
    assert "lease_owner = :lease_token" in statement
    assert "lease_expires_at > now()" in statement


@pytest.mark.asyncio
async def test_cannot_bind_artifact_before_verified_commit():
    repo = UploadSessionRepository(lambda: FakeSession(record()))
    with pytest.raises(ValueError, match="only at commit"):
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
    select_sql = db.statements[1][0]
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
    assert db.statements[0][1]["expected_sha256"] == DIGEST
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
            expected_state="committing", next_state="committed",
            artifact_id=str(uuid4()),
        )
    assert db.statements == []
