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
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
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


def _disposable_database_url(dsn: str):
    """Reject ambiguous asyncpg connection targets before any SQL opens."""
    try:
        parsed = make_url(dsn)
    except (ArgumentError, ValueError, TypeError):
        pytest.fail("Invalid disposable PostgreSQL connection URL")
    if (
        parsed.drivername not in ("postgresql", "postgresql+asyncpg")
        or parsed.database != _TEST_DB_NAME.lstrip("/")
        or not parsed.host
        or parsed.query
    ):
        pytest.fail("Refusing artifact proof outside an unambiguous disposable database")
    return parsed.set(drivername="postgresql+asyncpg")


@pytest.mark.parametrize("dsn", [
    "postgresql+asyncpg://user:password@localhost/karen_code_artifact_test?database=production",
    "postgresql+asyncpg://user:password@localhost/karen_code_artifact_test?host=production",
    "postgresql+asyncpg://user:password@localhost/karen_code_artifact_test?port=5433",
    "postgresql+asyncpg://user:password@localhost/production",
    "postgresql+asyncpg:///karen_code_artifact_test",
    "sqlite:///karen_code_artifact_test",
    "not a database URL",
])
async def test_disposable_database_target_override_denied_before_engine(dsn):
    with pytest.raises(pytest.fail.Exception):
        _disposable_database_url(dsn)


async def test_disposable_database_url_preserves_explicit_target():
    parsed = _disposable_database_url(
        "postgresql://test_user:test_password@localhost:5432/karen_code_artifact_test"
    )
    assert parsed.drivername == "postgresql+asyncpg"
    assert parsed.database == "karen_code_artifact_test"
    assert parsed.host == "localhost"
    assert not parsed.query


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
    parsed = _disposable_database_url(dsn)
    tenant = str(UUID(tenant_raw))
    owner = str(UUID(owner_raw))
    foreign_owner = str(UUID(other_raw))
    if owner == foreign_owner:
        pytest.fail("Foreign owner fixture must differ from artifact owner")

    engine = create_async_engine(
        parsed.set(drivername="postgresql+asyncpg"),
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
        # Verify the server's effective database and canonical migrated
        # archive-column schema *after* connecting and *before* any writes.
        # URL validation alone is not evidence of the actual server target.
        async with sessions() as session:
            database_name = (await session.execute(
                text("SELECT current_database()")
            )).scalar_one()
            if database_name != _TEST_DB_NAME.lstrip("/"):
                pytest.fail("Effective PostgreSQL database is not disposable")
            archive_column = (await session.execute(text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'files' "
                "AND column_name = 'deleted_at'"
            ))).scalar_one_or_none()
            if archive_column != "timestamp without time zone":
                pytest.fail("Canonical migrated files.deleted_at column is missing")

        # The fixture must already contain the real migrated files table and
        # authorized tenant/user rows. No schema or user creation happens here.
        async with sessions() as session:
            await session.execute(
                text(
                    "INSERT INTO files "
                    "(file_id, tenant_id, owner_user_id, name, mime_type, "
                    "bytes, storage_uri, sha256, metadata, created_at) "
                    "VALUES (:file_id, :tenant_id, "
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
                    "WHERE file_id = :file_id "
                    "AND tenant_id = :tenant_id "
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
                        "DELETE FROM files WHERE file_id = :file_id "
                        "AND tenant_id = :tenant_id"
                    ),
                    {"file_id": artifact, "tenant_id": tenant},
                )
                await session.commit()
        await engine.dispose()


@pytest.mark.skipif(
    os.getenv("KAREN_TEST_CODE_ARTIFACT_LIVE_STORAGE") != "1",
    reason="Requires explicit live Supabase Storage read-only acceptance opt-in",
)
async def test_live_supabase_object_read_with_disposable_postgres_owner_scope() -> None:
    """Read preseeded source bytes from real Storage without changing either service.

    This is deliberately NOT a production RLS test. The platform's configured
    credential may bypass Storage RLS; identity is always checked in the
    canonical repository's PostgreSQL owner/tenant query.
    """
    import re

    from ai_karen_engine.integrations.supabase_client import SupabasePlatformClient

    if os.getenv("KAREN_TEST_DISPOSABLE_DATABASE") != "1":
        pytest.fail("Live Storage acceptance requires disposable PostgreSQL opt-in")
    if os.getenv("KAREN_TEST_SUPABASE_DISPOSABLE") != "1":
        pytest.fail("Live Storage acceptance requires an explicitly disposable project")

    project_ref = os.getenv("KAREN_TEST_SUPABASE_PROJECT_REF", "")
    project_url = os.getenv("SUPABASE_PROJECT_URL", "")
    if (
        re.fullmatch(r"[a-z0-9]{20}", project_ref) is None
        or project_url != f"https://{project_ref}.supabase.co"
    ):
        pytest.fail("Live Storage target must match the explicitly named test project")

    dsn = os.getenv("KAREN_TEST_CODE_ARTIFACT_DATABASE_URL", "")
    if not dsn:
        pytest.fail("Missing disposable PostgreSQL connection URL")
    parsed = _disposable_database_url(dsn)

    def required_uuid(name: str) -> str:
        raw = os.getenv(name, "")
        try:
            parsed_uuid = str(UUID(raw))
        except (ValueError, TypeError, AttributeError):
            pytest.fail(f"Invalid opt-in fixture identity: {name}")
        if parsed_uuid != raw:
            pytest.fail(f"Noncanonical opt-in fixture identity: {name}")
        return parsed_uuid

    tenant = required_uuid("KAREN_TEST_ARTIFACT_TENANT_ID")
    owner = required_uuid("KAREN_TEST_ARTIFACT_OWNER_ID")
    foreign_owner = required_uuid("KAREN_TEST_ARTIFACT_OTHER_USER_ID")
    artifact = required_uuid("KAREN_TEST_LIVE_ARTIFACT_ID")
    if len({tenant, owner, foreign_owner, artifact}) != 4:
        pytest.fail("Live Storage proof requires distinct identities")

    expected_sha = os.getenv("KAREN_TEST_LIVE_ARTIFACT_SHA256", "")
    if re.fullmatch(r"[a-f0-9]{64}", expected_sha) is None:
        pytest.fail("A canonical preseeded artifact SHA-256 is required")
    if not any(
        os.getenv(name)
        for name in (
            "SUPABASE_SECRET_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
            "SUPABASE_PUBLISHABLE_KEY",
            "SUPABASE_ANON_KEY",
        )
    ):
        pytest.fail("Supabase test project credential is unavailable")

    # No uploads, bucket creation, metadata writes or archive mutations.
    # Confirm the fixture and expected digest before contacting Storage.
    engine = create_async_engine(parsed, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    platform = SupabasePlatformClient()
    try:
        async with sessions() as session:
            database_name = (
                await session.execute(text("SELECT current_database()"))
            ).scalar_one()
            if database_name != "karen_code_artifact_test":
                pytest.fail("Effective PostgreSQL database is not disposable")

            record = (
                await session.execute(
                    text(
                        "SELECT owner_user_id, tenant_id, name, storage_uri, "
                        "sha256, deleted_at FROM files "
                        "WHERE file_id = :artifact"
                    ),
                    {"artifact": artifact},
                )
            ).mappings().one_or_none()
            if record is None:
                pytest.fail("Expected preseeded artifact metadata is unavailable")
            if (
                str(record["tenant_id"]) != tenant
                or str(record["owner_user_id"]) != owner
                or record["deleted_at"] is not None
                or record["sha256"] != expected_sha
                or not isinstance(record["name"], str)
                or record["storage_uri"] != (
                    f"supabase://artifacts/{tenant}/{artifact}/{record['name']}"
                )
            ):
                pytest.fail("Preseeded artifact metadata does not match test scope")

        platform.initialize()
        if platform.storage is None or platform.url != project_url:
            pytest.fail("Canonical Supabase Storage client is unavailable")
        store = SupabaseArtifactStore(sessions, platform)

        foreign = await store.read_owner_active_code(artifact, tenant, foreign_owner)
        wrong_tenant = await store.read_owner_active_code(
            artifact, str(uuid4()), owner
        )
        assert not foreign.success and foreign.data is None
        assert not wrong_tenant.success and wrong_tenant.data is None
        assert foreign.error == wrong_tenant.error == "artifact_code_unavailable"

        granted = await store.read_owner_active_code(artifact, tenant, owner)
        assert granted.success and granted.data is not None
        assert granted.data.sha256 == expected_sha
        assert hashlib.sha256(granted.data.text.encode("utf-8")).hexdigest() == expected_sha
        assert granted.data.artifact_id == artifact
        assert granted.data.tenant_id == tenant
        assert granted.data.user_id == owner
    finally:
        platform.reset()
        await engine.dispose()


@pytest.mark.skipif(
    os.getenv("KAREN_TEST_DISPOSABLE_DATABASE") != "1"
    or os.getenv("KAREN_TEST_CODE_ARTIFACT_POSTGRES") != "1",
    reason="Requires explicit disposable PostgreSQL artifact acceptance opt-in",
)
async def test_for_share_read_serializes_concurrent_archive_and_revokes_next_read() -> None:
    """Hold a real repository read at Storage while PostgreSQL blocks archive."""
    import asyncio
    import threading

    from sqlalchemy.exc import DBAPIError

    dsn = os.getenv("KAREN_TEST_CODE_ARTIFACT_DATABASE_URL", "")
    tenant_raw = os.getenv("KAREN_TEST_ARTIFACT_TENANT_ID", "")
    owner_raw = os.getenv("KAREN_TEST_ARTIFACT_OWNER_ID", "")
    if not dsn or not tenant_raw or not owner_raw:
        pytest.fail("Explicit disposable database and seeded owner required")
    parsed = _disposable_database_url(dsn)
    tenant = str(UUID(tenant_raw))
    owner = str(UUID(owner_raw))
    engine = create_async_engine(parsed, pool_pre_ping=True, pool_size=3)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    artifact = str(uuid4())
    filename = "concurrent_archive.py"
    key = f"{tenant}/{artifact}/{filename}"
    digest = hashlib.sha256(_SOURCE).hexdigest()
    read_entered_storage = threading.Event()
    release_storage = threading.Event()
    bucket = MagicMock()

    def blocked_download(storage_key: str) -> bytes:
        assert storage_key == key
        read_entered_storage.set()
        if not release_storage.wait(timeout=10):
            raise TimeoutError("Repository source read was not released")
        return _SOURCE

    bucket.download.side_effect = blocked_download
    platform = SimpleNamespace(
        storage=SimpleNamespace(
            from_=lambda bucket_name: bucket if bucket_name == "artifacts" else None
        )
    )
    inserted = False

    def read_in_independent_thread():
        """Use a separate asyncpg engine, never share connections across loops."""
        async def run():
            reader_engine = create_async_engine(parsed, pool_pre_ping=True)
            reader_sessions = async_sessionmaker(reader_engine, expire_on_commit=False)
            try:
                reader_store = SupabaseArtifactStore(reader_sessions, platform)
                return await reader_store.read_owner_active_code(artifact, tenant, owner)
            finally:
                await reader_engine.dispose()

        return asyncio.run(run())

    try:
        async with sessions() as admin:
            assert (
                await admin.execute(text("SELECT current_database()"))
            ).scalar_one() == "karen_code_artifact_test"
            await admin.execute(
                text(
                    "INSERT INTO files "
                    "(file_id, tenant_id, owner_user_id, name, mime_type, "
                    "bytes, storage_uri, sha256, metadata, created_at) "
                    "VALUES (:id, CAST(:tenant AS uuid), CAST(:owner AS uuid), "
                    ":name, :mime, :bytes, :uri, :digest, '{}'::jsonb, NOW())"
                ),
                {
                    "id": artifact, "tenant": tenant, "owner": owner,
                    "name": filename, "mime": "text/x-python",
                    "bytes": len(_SOURCE), "uri": f"supabase://artifacts/{key}",
                    "digest": digest,
                },
            )
            await admin.commit()
            inserted = True

        # The real repository executes its SELECT FOR SHARE on its own async
        # connection before entering the synchronous Storage download.
        read_task = asyncio.create_task(asyncio.to_thread(read_in_independent_thread))
        try:
            assert await asyncio.to_thread(read_entered_storage.wait, 10), (
                "Canonical repository never reached the controlled Storage boundary"
            )
            assert not read_task.done(), "Repository read ended before archive"

            # The independent archive must collide with the repository's own
            # row lock. If the repository drops FOR SHARE or closes its
            # transaction early, UPDATE succeeds and this proof fails.
            async with sessions() as writer:
                await writer.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(DBAPIError) as blocked:
                    await writer.execute(
                        text(
                            "UPDATE files SET deleted_at = NOW() "
                            "WHERE file_id = :file_id AND tenant_id = :tenant_id "
                            "AND deleted_at IS NULL"
                        ),
                        {"file_id": artifact, "tenant_id": tenant},
                    )
                assert "lock timeout" in str(blocked.value).lower()
                await writer.rollback()
            assert not read_task.done(), "Source read escaped the held boundary"
        finally:
            release_storage.set()

        granted = await asyncio.wait_for(read_task, timeout=15)
        assert granted.success and granted.data is not None
        assert granted.data.text.encode("utf-8") == _SOURCE
        bucket.download.assert_called_once_with(key)

        async with sessions() as writer:
            changed = await writer.execute(
                text(
                    "UPDATE files SET deleted_at = NOW() "
                    "WHERE file_id = :file_id AND tenant_id = :tenant_id "
                    "AND deleted_at IS NULL"
                ),
                {"file_id": artifact, "tenant_id": tenant},
            )
            assert changed.rowcount == 1
            await writer.commit()

        # This call must refuse the archived record before Storage access.
        store = SupabaseArtifactStore(sessions, platform)
        revoked = await store.read_owner_active_code(artifact, tenant, owner)
        assert not revoked.success and revoked.data is None
        assert revoked.error == "artifact_code_unavailable"
        assert bucket.download.call_count == 1
    finally:
        release_storage.set()
        if inserted:
            async with sessions() as admin:
                await admin.execute(
                    text("DELETE FROM files WHERE file_id = :file_id"),
                    {"file_id": artifact},
                )
                await admin.commit()
        await engine.dispose()
