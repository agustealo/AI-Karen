"""CK-GEN-01D4B: real PostgreSQL non-bypass actor and artifact admission proof.

Only executes against the dedicated disposable PostgreSQL database created by
ckgen-artifact-postgres-proof.yml. It does not create production roles/policies.
The source bytes remain a controlled in-process fixture, not Supabase Storage.
"""

from __future__ import annotations

import hashlib
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.services.database.repositories.supabase_artifact_store import (
    SupabaseArtifactStore,
)

pytestmark = pytest.mark.asyncio

_ROLE = "ckgen_artifact_rls_actor"
_DATABASE = "karen_code_artifact_test"
_SOURCE = b"print('rls fixture; never execute')\n"


def _identity(name: str) -> str:
    raw = os.environ.get(name, "")
    try:
        canonical = str(UUID(raw))
    except (TypeError, ValueError, AttributeError) as exc:
        pytest.fail(f"Invalid disposable fixture identifier {name}: {type(exc).__name__}")
    if raw != canonical:
        pytest.fail(f"Noncanonical disposable fixture identifier {name}")
    return canonical


def _disposable_url():
    raw = os.environ.get("KAREN_TEST_CODE_ARTIFACT_DATABASE_URL", "")
    try:
        parsed = make_url(raw)
    except (ValueError, TypeError) as exc:
        pytest.fail(f"Invalid disposable database URL: {type(exc).__name__}")
    if (
        parsed.drivername not in ("postgresql", "postgresql+asyncpg")
        or parsed.database != _DATABASE
        or parsed.query
        or parsed.host not in ("127.0.0.1", "localhost")
        or parsed.port != 5432
    ):
        pytest.fail("Refusing RLS actor proof outside local disposable PostgreSQL")
    return parsed.set(drivername="postgresql+asyncpg")


@pytest.mark.skipif(
    os.environ.get("KAREN_TEST_DISPOSABLE_DATABASE") != "1"
    or os.environ.get("KAREN_TEST_CODE_ARTIFACT_RLS") != "1",
    reason="Requires explicit disposable PostgreSQL non-bypass RLS proof opt-in",
)
async def test_non_bypass_actor_rls_owner_archive_and_transaction_isolation() -> None:
    tenant_a = _identity("KAREN_TEST_ARTIFACT_TENANT_ID")
    tenant_b = _identity("KAREN_TEST_ARTIFACT_TENANT_B_ID")
    owner_a = _identity("KAREN_TEST_ARTIFACT_OWNER_ID")
    other_a = _identity("KAREN_TEST_ARTIFACT_OTHER_USER_ID")
    owner_b = _identity("KAREN_TEST_ARTIFACT_OWNER_B_ID")
    if len({tenant_a, tenant_b, owner_a, other_a, owner_b}) != 5:
        pytest.fail("RLS actor identities must all be distinct")

    engine = create_async_engine(_disposable_url(), pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    artifact_a, artifact_b = str(uuid4()), str(uuid4())
    filename = "actor_proof.py"
    digest = hashlib.sha256(_SOURCE).hexdigest()
    inserted = False
    bucket = MagicMock()
    bucket.download.return_value = _SOURCE
    platform = SimpleNamespace(
        storage=SimpleNamespace(from_=lambda name: bucket if name == "artifacts" else None)
    )

    async def actor_session(tenant: str | None, user: str | None = None):
        """Apply a transaction-local non-bypass role and scoped identity."""
        session = sessions()
        try:
            await session.execute(text(f"SET LOCAL ROLE {_ROLE}"))
            if tenant is not None:
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant},
                )
            if user is not None:
                await session.execute(
                    text("SELECT set_config('app.current_user_id', :user, true)"),
                    {"user": user},
                )
            return session
        except BaseException:
            await session.close()
            raise

    try:
        async with sessions() as admin:
            assert (
                await admin.execute(text("SELECT current_database()"))
            ).scalar_one() == _DATABASE

            role = (
                await admin.execute(
                    text(
                        "SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles "
                        "WHERE rolname = :role"
                    ),
                    {"role": _ROLE},
                )
            ).one()
            assert tuple(role) == (False, False, False)

            policy = (
                await admin.execute(
                    text(
                        "SELECT relrowsecurity AS rowsecurity, relforcerowsecurity FROM pg_class "
                        "WHERE oid = 'public.files'::regclass"
                    )
                )
            ).one()
            assert policy.rowsecurity is True
            assert (
                await admin.execute(
                    text(
                        "SELECT qual, with_check FROM pg_policies "
                        "WHERE schemaname='public' AND tablename='files' "
                        "AND policyname='files_tenant_isolation'"
                    )
                )
            ).one() is not None

            for artifact, tenant, owner in (
                (artifact_a, tenant_a, owner_a),
                (artifact_b, tenant_b, owner_b),
            ):
                await admin.execute(
                    text(
                        "INSERT INTO files "
                        "(file_id, tenant_id, owner_user_id, name, mime_type, "
                        "bytes, storage_uri, sha256, metadata, created_at) "
                        "VALUES (:file_id, CAST(:tenant AS uuid), "
                        "CAST(:owner AS uuid), :name, :mime, :bytes, :uri, "
                        ":digest, '{}'::jsonb, NOW())"
                    ),
                    {
                        "file_id": artifact,
                        "tenant": tenant,
                        "owner": owner,
                        "name": filename,
                        "mime": "text/x-python",
                        "bytes": len(_SOURCE),
                        "uri": f"supabase://artifacts/{tenant}/{artifact}/{filename}",
                        "digest": digest,
                    },
                )
            await admin.commit()
            inserted = True

        for tenant, visible, hidden in (
            (tenant_a, artifact_a, artifact_b),
            (tenant_b, artifact_b, artifact_a),
        ):
            async with await actor_session(tenant) as session:
                assert (
                    await session.execute(text("SELECT current_user"))
                ).scalar_one() == _ROLE
                visible_rows = (
                    await session.execute(
                        text("SELECT file_id FROM files ORDER BY file_id")
                    )
                ).scalars().all()
                assert visible_rows == [visible]
                assert hidden not in visible_rows
                assert (
                    await session.execute(
                        text("UPDATE files SET deleted_at = NOW() "
                             "WHERE file_id = :foreign_id"),
                        {"foreign_id": hidden},
                    )
                ).rowcount == 0
                await session.rollback()

        # Missing tenant context must never return source rows. Database
        # configurations may deny it by either an empty result or SQL error.
        async with await actor_session(None) as session:
            try:
                rows = (await session.execute(text("SELECT file_id FROM files"))).all()
            except Exception:
                await session.rollback()
            else:
                assert rows == []
                await session.rollback()

        # The real repository is exercised under a non-bypass role for every
        # fresh transaction, not just an administrative query with a predicate.
        @asynccontextmanager
        async def owner_scoped_session():
            async with await actor_session(tenant_a, owner_a) as session:
                yield session

        store_a = SupabaseArtifactStore(
            session_factory=owner_scoped_session,
            storage_client=platform,
        )
        granted = await store_a.read_owner_active_code(artifact_a, tenant_a, owner_a)
        assert granted.success and granted.data is not None
        assert granted.data.text.encode() == _SOURCE
        bucket.download.assert_called_once_with(
            f"{tenant_a}/{artifact_a}/{filename}"
        )

        denied_owner = await store_a.read_owner_active_code(
            artifact_a, tenant_a, other_a
        )
        denied_tenant = await store_a.read_owner_active_code(
            artifact_b, tenant_b, owner_b
        )
        assert not denied_owner.success and denied_owner.data is None
        assert not denied_tenant.success and denied_tenant.data is None
        assert bucket.download.call_count == 1

        # Committed archive must revoke the original owner, even though the
        # controlled object bytes remain in the test bucket.
        async with sessions() as admin:
            assert (
                await admin.execute(
                    text(
                        "UPDATE files SET deleted_at = NOW() "
                        "WHERE file_id = :id AND tenant_id = CAST(:tenant AS uuid)"
                    ),
                    {"id": artifact_a, "tenant": tenant_a},
                )
            ).rowcount == 1
            await admin.commit()

        revoked = await store_a.read_owner_active_code(artifact_a, tenant_a, owner_a)
        assert not revoked.success and revoked.data is None
        assert denied_owner.error == revoked.error == "artifact_code_unavailable"
        assert bucket.download.call_count == 1

        # Reacquired pooled session should have no lingering role or tenant
        # grant from SET LOCAL / set_config(..., true).
        async with sessions() as admin:
            assert (
                await admin.execute(text("SELECT current_user"))
            ).scalar_one() != _ROLE
    finally:
        if inserted:
            async with sessions() as admin:
                await admin.execute(
                    text("DELETE FROM files WHERE file_id IN (:one, :two)"),
                    {"one": artifact_a, "two": artifact_b},
                )
                await admin.commit()
        await engine.dispose()
