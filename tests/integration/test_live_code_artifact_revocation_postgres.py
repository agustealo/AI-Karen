"""CK-GEN-01D2 opt-in PostgreSQL evidence for owner and archive revocation.

Run only on an explicitly disposable, migrated and seeded PostgreSQL
database called karen_code_artifact_test. This never touches production
records. Supabase object bytes are deliberately supplied by an in-process
test bucket; a live object-store and signed-in browser run remain separate.
"""

from __future__ import annotations

import hashlib
import os
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.services.database.repositories.supabase_artifact_store import (
    SupabaseArtifactStore,
)

pytestmark = pytest.mark.asyncio

_SOURCE = b"print('disposable source, never execute')\n"
_TEST_DB_NAME = "/karen_code_artifact_test"


@pytest.mark.skipif(
    os.getenv("KAREN_TEST_DISPOSABLE_DATABASE") != "1"
    or os.getenv("KAREN_TEST_CODE_ARTIFACT_POSTGRES") != "1",
    reason="Requires explicit disposable PostgreSQL artifact acceptance opt-in",
)
async def test_real_postgres_owner_read_archive_and_foreign_owner_denial() -> None:
    dsn = os.getenv("KAREN_TEST_CODE_ARTIFACT_DATABASE_URL", "")
    tenant_raw = os.getenv("KAREN_TEST_ARTIFACT_TENANT_ID", "")
    owner_raw = os.getenv("KAREN_TEST_ARTIFACT_OWNER_ID", "")
    other_raw = os.getenv("KAREN_TEST_ARTIFACT_OTHER_USER_ID", "")
    if not dsn or not all((tenant_raw, owner_raw, other_raw)):
        pytest.fail("Explicit disposable database URL and seeded principals required")
    parsed = urlparse(dsn)
    if (
        parsed.scheme not in ("postgresql", "postgresql+asyncpg")
        or parsed.path != _TEST_DB_NAME
    ):
        pytest.fail("Refusing artifact proof outside /karen_code_artifact_test")
    tenant = str(UUID(tenant_raw))
    owner = str(UUID(owner_raw))
    foreign_owner = str(UUID(other_raw))
    if owner == foreign_owner:
        pytest.fail("Foreign owner fixture must differ from artifact owner")

    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://", 1),
        pool_pre_ping=True,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    artifact = str(uuid4())
    filename = "disposable_artifact.py"
    key = f"{tenant}/{artifact}/{filename}"
    digest = hashlib.sha256(_SOURCE).hexdigest()

    bucket = MagicMock()
    bucket.download.return_value = _SOURCE
    platform = SimpleNamespace(
        storage=SimpleNamespace(from_=lambda name: (
            bucket if name == "artifacts" else None
        )),
    )
    store = SupabaseArtifactStore(sessions, platform)
    inserted = False

    try:
        # The fixture must already contain the real migrated files table and
        # authorized tenant/user rows. No schema or user creation happens here.
        async with sessions() as session:
            await session.execute(
                text(
                    "INSERT INTO files "
                    "(file_id, tenant_id, owner_user_id, name, mime_type, "
                    "bytes, storage_uri, sha256, metadata, created_at) "
                    "VALUES (CAST(:file_id AS uuid), CAST(:tenant_id AS uuid), "
                    "CAST(:owner_id AS uuid), :name, :mime_type, :size, "
                    ":storage_uri, :sha256, CAST(:metadata AS jsonb), NOW())"
                ),
                {
                    "file_id": artifact,
                    "tenant_id": tenant,
                    "owner_id": owner,
                    "name": filename,
                    "mime_type": "text/x-python",
                    "size": len(_SOURCE),
                    "storage_uri": f"supabase://artifacts/{key}",
                    "sha256": digest,
                    "metadata": "{}",
                },
            )
            await session.commit()
            inserted = True

        # Real PostgreSQL SELECT ... FOR SHARE, tenant, owner, active filter.
        granted = await store.read_owner_active_code(artifact, tenant, owner)
        assert granted.success
        assert granted.data is not None
        assert granted.data.text.encode("utf-8") == _SOURCE
        assert granted.data.sha256 == digest
        bucket.download.assert_called_once_with(key)

        denied = await store.read_owner_active_code(
            artifact, tenant, foreign_owner,
        )
        assert not denied.success
        assert denied.data is None
        assert bucket.download.call_count == 1

        # Archive in a separately committed transaction. The same owner must
        # no longer receive bytes even when the object is still in storage.
        async with sessions() as session:
            changed = await session.execute(
                text(
                    "UPDATE files SET deleted_at = NOW() "
                    "WHERE file_id = CAST(:file_id AS uuid) "
                    "AND tenant_id = CAST(:tenant_id AS uuid) "
                    "AND owner_user_id = CAST(:owner_id AS uuid) "
                    "AND deleted_at IS NULL"
                ),
                {
                    "file_id": artifact, "tenant_id": tenant,
                    "owner_id": owner,
                },
            )
            assert changed.rowcount == 1
            await session.commit()

        revoked = await store.read_owner_active_code(artifact, tenant, owner)
        assert not revoked.success
        assert revoked.data is None
        assert bucket.download.call_count == 1

        # An archived artifact is not eligible, even for its original owner.
        assert revoked.error == denied.error == "artifact_code_unavailable"
    finally:
        if inserted:
            async with sessions() as session:
                await session.execute(
                    text(
                        "DELETE FROM files WHERE file_id = CAST(:file_id AS uuid) "
                        "AND tenant_id = CAST(:tenant_id AS uuid)"
                    ),
                    {"file_id": artifact, "tenant_id": tenant},
                )
                await session.commit()
        await engine.dispose()
