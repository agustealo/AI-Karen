"""Real disposable PostgreSQL proof of the upload ledger's default-deny RLS.

The CI workflow owns database creation, migration and disposable actor role.
No production database or production role is modified.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.services.database.repositories.upload_session import (
    UploadSessionConflict,
    UploadSessionRepository,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("KAREN_TEST_DISPOSABLE_DATABASE") != "1"
        or os.environ.get("KAREN_TEST_CODE_ARTIFACT_RLS") != "1",
        reason="Requires the disposable artifact PostgreSQL proof database",
    ),
]


async def test_upload_session_migration_rls_and_repository_contract() -> None:
    url = make_url(os.environ["KAREN_TEST_CODE_ARTIFACT_DATABASE_URL"])
    assert url.drivername in ("postgresql", "postgresql+asyncpg")
    assert url.host in ("127.0.0.1", "localhost")
    assert url.port == 5432 and url.database == "karen_code_artifact_test"
    assert not url.query

    tenant = str(UUID(os.environ["KAREN_TEST_ARTIFACT_TENANT_ID"]))
    owner = str(UUID(os.environ["KAREN_TEST_ARTIFACT_OWNER_ID"]))
    foreign_owner = str(UUID(os.environ["KAREN_TEST_ARTIFACT_OTHER_USER_ID"]))
    foreign_tenant = str(UUID(os.environ["KAREN_TEST_ARTIFACT_TENANT_B_ID"]))
    engine = create_async_engine(url.set(drivername="postgresql+asyncpg"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = UploadSessionRepository(factory)
    key = uuid4().hex + uuid4().hex
    digest = "a" * 64
    try:
        async with factory() as db:
            assert (await db.execute(text("SELECT current_database()"))).scalar_one() == "karen_code_artifact_test"
            column = (await db.execute(text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='artifact_upload_sessions' "
                "AND column_name='tenant_id'"
            ))).scalar_one()
            assert column == "uuid"
            rls = (await db.execute(text(
                "SELECT relrowsecurity, relforcerowsecurity "
                "FROM pg_class WHERE oid='public.artifact_upload_sessions'::regclass"
            ))).one()
            assert tuple(rls) == (True, True)
            policies = (await db.execute(text(
                "SELECT count(*) FROM pg_policies "
                "WHERE schemaname='public' AND tablename='artifact_upload_sessions'"
            ))).scalar_one()
            assert policies == 0
            role = (await db.execute(text(
                "SELECT rolsuper, rolbypassrls FROM pg_roles "
                "WHERE rolname='ckgen_artifact_rls_actor'"
            ))).one()
            assert tuple(role) == (False, False)

        first = await repo.create_or_get(
            tenant_id=tenant, owner_user_id=owner, destination_id="explorer",
            recipe="store_only", idempotency_key_hash=key,
            manifest_sha256=digest, expected_bytes=42,
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        again = await repo.create_or_get(
            tenant_id=tenant, owner_user_id=owner, destination_id="explorer",
            recipe="store_only", idempotency_key_hash=key,
            manifest_sha256=digest, expected_bytes=42,
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        assert first.session_id == again.session_id
        with pytest.raises(UploadSessionConflict):
            await repo.create_or_get(
                tenant_id=tenant, owner_user_id=owner, destination_id="other",
                recipe="store_only", idempotency_key_hash=key,
                manifest_sha256=digest, expected_bytes=42,
                expires_at=datetime.utcnow() + timedelta(hours=1),
            )
        assert await repo.transition(
            tenant_id=tenant, owner_user_id=foreign_owner,
            session_id=first.session_id, expected_state="created",
            next_state="receiving",
        ) is None
        assert await repo.transition(
            tenant_id=foreign_tenant, owner_user_id=owner,
            session_id=first.session_id, expected_state="created",
            next_state="receiving",
        ) is None

        async with factory() as db:
            await db.execute(text("SET LOCAL ROLE ckgen_artifact_rls_actor"))
            await db.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                {"tenant": tenant},
            )
            # The migration revokes table privileges as well as providing
            # default-deny FORCE RLS. PostgreSQL may deny before RLS executes.
            with pytest.raises(ProgrammingError, match="permission denied"):
                await db.execute(text(
                    "SELECT count(*) FROM public.artifact_upload_sessions"
                ))
            await db.rollback()

        async with factory() as db:
            await db.execute(text("SET LOCAL ROLE ckgen_artifact_rls_actor"))
            with pytest.raises(ProgrammingError, match="permission denied"):
                await db.execute(text(
                    "UPDATE public.artifact_upload_sessions "
                    "SET state='cancelled' WHERE session_id=:id"
                ), {"id": UUID(first.session_id)})
            await db.rollback()

        # One canonical artifact cannot be bound to two durable sessions,
        # even if concurrent workers carry distinct idempotency keys.
        second = await repo.create_or_get(
            tenant_id=tenant, owner_user_id=owner, destination_id="explorer",
            recipe="store_only", idempotency_key_hash=uuid4().hex + uuid4().hex,
            manifest_sha256=digest, expected_bytes=42,
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        artifact_id = str(uuid4())
        async with factory() as db:
            await db.execute(text(
                "INSERT INTO public.files "
                "(file_id, tenant_id, owner_user_id, name, mime_type, bytes, "
                "storage_uri, sha256, metadata, created_at) VALUES "
                "(:id, CAST(:tenant AS uuid), CAST(:owner AS uuid), "
                "'proof.bin', 'application/octet-stream', 42, :uri, "
                ":digest, '{}'::jsonb, now())"
            ), {
                "id": artifact_id, "tenant": tenant, "owner": owner,
                "uri": f"supabase://artifacts/{tenant}/{artifact_id}/content",
                "digest": digest,
            })
            await db.execute(text(
                "UPDATE public.artifact_upload_sessions SET artifact_id=:artifact "
                "WHERE session_id=:session"
            ), {"artifact": artifact_id, "session": UUID(first.session_id)})
            await db.commit()
        async with factory() as db:
            with pytest.raises(IntegrityError):
                await db.execute(text(
                    "UPDATE public.artifact_upload_sessions SET artifact_id=:artifact "
                    "WHERE session_id=:session"
                ), {"artifact": artifact_id, "session": UUID(second.session_id)})
            await db.rollback()

        receiving = await repo.transition(
            tenant_id=tenant, owner_user_id=owner,
            session_id=first.session_id, expected_state="created",
            next_state="receiving",
        )
        assert receiving is not None and receiving.state == "receiving"
        assert await repo.transition(
            tenant_id=tenant, owner_user_id=owner,
            session_id=first.session_id, expected_state="created",
            next_state="receiving",
        ) is None
        # SQL fixtures represent a previously staged transfer; the ledger is
        # not itself a Storage reader. No object-upload success is inferred.
        # Equal byte counts must not substitute for a pinned content digest.
        async def insert_candidate(expected_digest, artifact_digest):
            item = await repo.create_or_get(
                tenant_id=tenant, owner_user_id=owner,
                destination_id="explorer", recipe="store_only",
                idempotency_key_hash=uuid4().hex + uuid4().hex,
                manifest_sha256=digest, expected_bytes=42,
                expected_sha256=expected_digest,
                expires_at=datetime.utcnow() + timedelta(hours=1),
            )
            candidate_id = str(uuid4())
            async with factory() as db:
                await db.execute(text(
                    "INSERT INTO public.files "
                    "(file_id, tenant_id, owner_user_id, name, mime_type, bytes, "
                    "storage_uri, sha256, metadata, created_at) VALUES "
                    "(:id, CAST(:tenant AS uuid), CAST(:owner AS uuid), "
                    "'generated.txt', 'text/plain', 42, :uri, "
                    ":digest, '{}'::jsonb, now())"
                ), {
                    "id": candidate_id, "tenant": tenant, "owner": owner,
                    "uri": f"supabase://artifacts/{tenant}/{candidate_id}/content",
                    "digest": artifact_digest,
                })
                await db.execute(text(
                    "UPDATE public.artifact_upload_sessions "
                    "SET state='committing', received_bytes=expected_bytes "
                    "WHERE session_id=:session AND tenant_id=CAST(:tenant AS uuid) "
                    "AND owner_user_id=CAST(:owner AS uuid)"
                ), {
                    "session": UUID(item.session_id),
                    "tenant": tenant, "owner": owner,
                })
                await db.commit()
            return item, candidate_id

        for expected_digest, artifact_digest in (
            (None, digest), (digest, "b" * 64), (digest, digest),
        ):
            item, candidate_id = await insert_candidate(expected_digest, artifact_digest)
            assert item.expected_sha256 == expected_digest
            result = await repo.transition(
                tenant_id=tenant, owner_user_id=owner,
                session_id=item.session_id, expected_state="committing",
                next_state="committed", artifact_id=candidate_id,
            )
            if expected_digest is not None and expected_digest == artifact_digest:
                assert result is not None
                assert result.state == "committed"
                assert result.artifact_id == candidate_id
                assert result.expected_sha256 == expected_digest
            else:
                assert result is None
                async with factory() as db:
                    state, binding = (await db.execute(text(
                        "SELECT state, artifact_id FROM public.artifact_upload_sessions "
                        "WHERE session_id=:session"
                    ), {"session": UUID(item.session_id)})).one()
                    assert state == "committing" and binding is None
    finally:
        await engine.dispose()
