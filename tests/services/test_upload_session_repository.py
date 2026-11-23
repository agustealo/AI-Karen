"""Upload session repository boundary tests with deterministic SQL doubles."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_karen_engine.services.database.repositories.upload_session import (
    UploadSessionConflict,
    UploadSessionRepository,
)


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
        "tenant_id": "tenant-a",
        "owner_user_id": OWNER,
        "destination_id": "explorer",
        "recipe": "store_only",
        "state": "created",
        "manifest_sha256": DIGEST,
        "expected_bytes": 42,
        "received_bytes": 0,
        "artifact_id": None,
    }


@pytest.mark.asyncio
async def test_create_or_get_reuses_matching_manifest_and_scopes_queries():
    db = FakeSession(record())
    repo = UploadSessionRepository(lambda: db)
    result = await repo.create_or_get(
        tenant_id="tenant-a", owner_user_id=OWNER,
        destination_id="explorer", recipe="store_only",
        idempotency_key_hash=KEY, manifest_sha256=DIGEST,
        expected_bytes=42, expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    assert result.session_id == SESSION
    assert db.committed
    assert all(params["tenant_id"] == "tenant-a" for _, params in db.statements)
    assert all(params["owner_user_id"] == OWNER for _, params in db.statements)
    assert "ON CONFLICT" in db.statements[0][0]
    assert "FOR UPDATE" in db.statements[1][0]


@pytest.mark.asyncio
async def test_conflicting_idempotency_manifest_fails_closed():
    db = FakeSession(record())
    repo = UploadSessionRepository(lambda: db)
    with pytest.raises(UploadSessionConflict):
        await repo.create_or_get(
            tenant_id="tenant-a", owner_user_id=OWNER,
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
        tenant_id="tenant-a", owner_user_id=OWNER, session_id=SESSION,
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
            tenant_id="tenant-a", owner_user_id=OWNER, session_id=SESSION,
            expected_state="created", next_state="committed",
        )
    with pytest.raises(ValueError):
        await repo.transition(
            tenant_id="tenant-a", owner_user_id=OWNER, session_id=SESSION,
            expected_state="committing", next_state="committed",
        )


@pytest.mark.asyncio
async def test_committed_transition_requires_active_owner_matched_artifact():
    db = FakeSession({**record(), "state": "committing"})
    repo = UploadSessionRepository(lambda: db)
    artifact_id = str(uuid4())
    await repo.transition(
        tenant_id="tenant-a", owner_user_id=OWNER, session_id=SESSION,
        expected_state="committing", next_state="committed",
        artifact_id=artifact_id,
    )
    statement = db.statements[0][0]
    assert "received_bytes = expected_bytes" in statement
    assert "FROM public.files AS artifact" in statement
    assert "artifact.tenant_id = :tenant_id" in statement
    assert "artifact.owner_user_id = :owner_user_id" in statement
    assert "artifact.deleted_at IS NULL" in statement
    assert "artifact.bytes = expected_bytes" in statement
    assert "artifact.sha256 = expected_sha256" in statement
