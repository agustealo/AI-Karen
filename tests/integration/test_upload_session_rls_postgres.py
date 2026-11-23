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
            assert (await db.execute(text(
                "SELECT count(*) FROM public.artifact_upload_sessions"
            ))).scalar_one() == 0
            with pytest.raises(Exception):
                await db.execute(text(
                    "UPDATE public.artifact_upload_sessions "
                    "SET state='cancelled' WHERE session_id=:id"
                ), {"id": UUID(first.session_id)})
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
    finally:
        await engine.dispose()
