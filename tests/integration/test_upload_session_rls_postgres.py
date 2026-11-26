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
        # A metadata-only commit is no longer a legal transition. The
        # bounded readback path below is the sole finalization owner.
        with pytest.raises(ValueError, match="Illegal upload state"):
            await repo.transition(
                tenant_id=tenant, owner_user_id=owner,
                session_id=first.session_id, expected_state="committing",
                next_state="committed", artifact_id=first.session_id,
                lease_token=str(uuid4()),
            )
        # Exercise the new staging and lease path without manually setting
        # state. This proves SQL admission, not a real object transfer.
        import asyncio

        staged_session = await repo.create_or_get(
            tenant_id=tenant, owner_user_id=owner, destination_id="explorer",
            recipe="store_only", idempotency_key_hash=uuid4().hex + uuid4().hex,
            manifest_sha256=digest, expected_bytes=42, expected_sha256=digest,
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        scope = dict(tenant_id=tenant, owner_user_id=owner, session_id=staged_session.session_id)
        assert await repo.transition(
            **scope, expected_state="created", next_state="receiving",
        ) is not None
        assert await repo.record_staged(**scope, observed_bytes=41, observed_sha256=digest) is None
        assert await repo.record_staged(**scope, observed_bytes=42, observed_sha256="b" * 64) is None
        assert await repo.record_staged(
            **{**scope, "owner_user_id": foreign_owner},
            observed_bytes=42, observed_sha256=digest,
        ) is None
        staged = await repo.record_staged(**scope, observed_bytes=42, observed_sha256=digest)
        assert staged is not None and staged.state == "staged" and staged.received_bytes == 42
        deadline = datetime.utcnow() + timedelta(minutes=5)
        claims = await asyncio.gather(*(
            repo.claim_commit(**scope, lease_expires_at=deadline) for _ in range(2)
        ))
        winners = [claim for claim in claims if claim is not None]
        assert len(winners) == 1 and winners[0].lease_owner
        assert winners[0].storage_key == f"{tenant}/{staged_session.session_id}/content"
        assert await repo.transition(
            **scope, expected_state="committing", next_state="reconcile_required",
            lease_token=str(uuid4()),
        ) is None
        assert await repo.mark_expired_commit_uncertain(**scope) is None
        async with factory() as db:
            await db.execute(text(
                "UPDATE public.artifact_upload_sessions "
                "SET lease_expires_at=now()-interval '1 second' WHERE session_id=:session"
            ), {"session": UUID(staged_session.session_id)})
            await db.commit()
        assert await repo.transition(
            **scope, expected_state="committing", next_state="reconcile_required",
            lease_token=winners[0].lease_owner,
        ) is None
        uncertain = await repo.mark_expired_commit_uncertain(**scope)
        assert uncertain is not None and uncertain.state == "reconcile_required"
        assert uncertain.lease_owner is None
        assert await repo.claim_commit(**scope, lease_expires_at=deadline) is None

        # Recovery is deliberately read-only with respect to Storage. The
        # real PostgreSQL check below uses a bounded-reader double, not live
        # object bytes. Real reader integrity is tested in the existing suite.
        import hashlib
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from ai_karen_engine.services.database.repositories.artifact_store import VerifiedArtifactText

        body = "verified generated text"
        content_digest = hashlib.sha256(body.encode()).hexdigest()
        pending = await repo.create_or_get(
            tenant_id=tenant, owner_user_id=owner, destination_id="explorer",
            recipe="store_only", idempotency_key_hash=uuid4().hex + uuid4().hex,
            manifest_sha256=digest, expected_bytes=len(body.encode()),
            expected_sha256=content_digest,
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        recovery_scope = dict(tenant_id=tenant, owner_user_id=owner, session_id=pending.session_id)
        await repo.transition(**recovery_scope, expected_state="created", next_state="receiving")
        await repo.record_staged(
            **recovery_scope, observed_bytes=len(body.encode()), observed_sha256=content_digest,
        )
        lease = await repo.claim_commit(**recovery_scope, lease_expires_at=deadline)
        assert lease is not None
        claim_args = dict(
            **recovery_scope, lease_token=lease.lease_owner,
            observed_bytes=len(body.encode()), observed_sha256=content_digest,
        )
        assert await repo.consume_write_claim(
            **{**claim_args, "observed_sha256": "c" * 64},
        ) is None
        spent = await asyncio.gather(*(
            repo.consume_write_claim(**claim_args) for _ in range(2)
        ))
        assert sum(item is not None for item in spent) == 1
        assert next(item for item in spent if item is not None).state == "reconcile_required"
        assert await repo.consume_write_claim(**claim_args) is None
        async with factory() as db:
            await db.execute(text(
                "INSERT INTO public.files "
                "(file_id, tenant_id, owner_user_id, name, mime_type, bytes, "
                "storage_uri, sha256, metadata, created_at) VALUES "
                "(:id, CAST(:tenant AS uuid), CAST(:owner AS uuid), "
                "'generated.txt', 'text/plain', :size, :uri, "
                ":digest, '{}'::jsonb, now())"
            ), {
                "id": pending.session_id, "tenant": tenant, "owner": owner,
                "size": len(body.encode()), "digest": content_digest,
                "uri": f"supabase://artifacts/{lease.storage_key}",
            })
            await db.commit()
        def reader(source_id=pending.session_id, source_text=body):
            return SimpleNamespace(read_owner_active_text_bounded=AsyncMock(
                return_value=SimpleNamespace(success=True, data=VerifiedArtifactText(
                    artifact_id=source_id, tenant_id=tenant, user_id=owner,
                    filename="generated.txt", mime_type="text/plain",
                    sha256=content_digest, text=source_text,
                )),
            ))
        assert await repo.reconcile_verified_text(
            **recovery_scope, artifact_store=reader(source_id=str(uuid4())),
        ) is None
        assert await repo.reconcile_verified_text(
            **recovery_scope, artifact_store=reader(source_text="x" * len(body)),
        ) is None
        denied_reader = reader()
        assert await repo.reconcile_verified_text(
            **{**recovery_scope, "owner_user_id": foreign_owner}, artifact_store=denied_reader,
        ) is None
        denied_reader.read_owner_active_text_bounded.assert_not_awaited()
        # Matching bytes from the reader cannot certify mismatched SQL
        # digest/size/owner/path metadata at finalization.
        async with factory() as db:
            await db.execute(text(
                "UPDATE public.files SET sha256=:digest WHERE file_id=:id"
            ), {"digest": "b" * 64, "id": pending.session_id})
            await db.commit()
        assert await repo.reconcile_verified_text(**recovery_scope, artifact_store=reader()) is None
        async with factory() as db:
            await db.execute(text(
                "UPDATE public.files SET sha256=:digest WHERE file_id=:id"
            ), {"digest": content_digest, "id": pending.session_id})
            await db.commit()
        recovered = await repo.reconcile_verified_text(**recovery_scope, artifact_store=reader())
        assert recovered is not None and recovered.state == "committed"
        assert recovered.artifact_id == pending.session_id
        assert await repo.reconcile_verified_text(**recovery_scope, artifact_store=reader()) is None
    finally:
        await engine.dispose()
