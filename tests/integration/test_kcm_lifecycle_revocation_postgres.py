"""Real PostgreSQL KCM revocation hooks, not proof of training permission.

Uses a dedicated disposable database and canonical migration SQL. Every
assertion observes committed database state, not mocked trigger behavior.
Never run against the application database.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest


pytestmark = pytest.mark.asyncio

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("22222222-2222-4222-8222-222222222222")
USER_A = uuid.UUID("33333333-3333-4333-8333-333333333333")
USER_B = uuid.UUID("44444444-4444-4444-8444-444444444444")
REVISION = "a" * 64


async def _scoped(
    connection: asyncpg.Connection,
    tenant: uuid.UUID,
    user: uuid.UUID,
    sql: str,
    *args: object,
) -> object:
    async with connection.transaction():
        await connection.execute(
            "SELECT set_config('app.current_tenant_id',$1,true),"
            "set_config('app.current_user_id',$2,true)",
            str(tenant), str(user),
        )
        return await connection.fetchval(sql, *args)


async def _make_source(
    connection: asyncpg.Connection,
    tenant: uuid.UUID,
    user: uuid.UUID,
    source: uuid.UUID,
    *,
    revision: str = REVISION,
    insert_lineage: bool = True,
) -> None:
    await connection.execute(
        "INSERT INTO public.memory_event "
        "(event_id,tenant_id,user_id,payload_hash,event_type,"
        "payload,consent_state,sensitivity_class) "
        "VALUES($1,$2,$3,$4,'memory_persisted',"
        "'{}'::jsonb,'granted','normal')",
        source, tenant, user, revision,
    )
    if insert_lineage:
        await connection.execute(
            "INSERT INTO public.kcm_dataset_source_lineage "
            "(tenant_id,user_id,dataset_id,dataset_version,assessment_id,"
            "source_event_id,source_revision,manifest_sha256,split,leakage_group_id) "
            "VALUES($1,$2,$3,1,$4,$5,$6,$7,'train',$8)",
            tenant, user, uuid.uuid4(), uuid.uuid4(),
            source, revision, "b" * 64, f"case-{source}",
        )


async def _epoch(
    connection: asyncpg.Connection, tenant: uuid.UUID, user: uuid.UUID
) -> int:
    value = await connection.fetchval(
        "SELECT deletion_epoch FROM public.kcm_training_scope_state "
        "WHERE tenant_id=$1 AND user_id=$2",
        tenant, user,
    )
    assert isinstance(value, int)
    return value


async def _source_status(
    connection: asyncpg.Connection, source: uuid.UUID
) -> str:
    value = await connection.fetchval(
        "SELECT lineage_status FROM public.kcm_dataset_source_lineage "
        "WHERE source_event_id=$1", source,
    )
    assert isinstance(value, str)
    return value


async def test_live_kcm_memory_consent_privacy_revocation_is_atomic() -> None:
    dsn = os.getenv("KCM_LIFECYCLE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("KCM_LIFECYCLE_TEST_DATABASE_URL not configured")
    if urlparse(dsn).path != "/karen_kcm_lifecycle_test":
        pytest.fail("KCM lifecycle proof requires /karen_kcm_lifecycle_test only")

    pg_dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncpg.connect(pg_dsn)
    try:
        await conn.execute(
            "CREATE TABLE public.tenants(id uuid PRIMARY KEY);"
            "CREATE TABLE public.auth_users("
            "user_id uuid PRIMARY KEY,tenant_id uuid NOT NULL);"
            "CREATE TABLE public.memory_event("
            "event_id uuid PRIMARY KEY,"
            "tenant_id uuid NOT NULL,user_id uuid NOT NULL,"
            "payload_hash varchar(64) NOT NULL,"
            "event_type varchar(50) NOT NULL,"
            "valid_to timestamp without time zone,"
            "consent_state varchar(50) DEFAULT 'granted',"
            "sensitivity_class varchar(50) DEFAULT 'normal',"
            "payload jsonb NOT NULL DEFAULT '{}'::jsonb,"
            "supersedes uuid);"
            "CREATE TABLE public.consent_scope("
            "scope_id uuid PRIMARY KEY,"
            "tenant_id uuid NOT NULL,user_id uuid NOT NULL,"
            "scope_name varchar(100) NOT NULL,"
            "is_granted boolean NOT NULL DEFAULT TRUE,"
            "revoked_at timestamp without time zone);"
            "CREATE TABLE public.privacy_requests("
            "request_id uuid PRIMARY KEY,"
            "tenant_id uuid NOT NULL,user_id uuid NOT NULL,"
            "request_type varchar(32) NOT NULL,"
            "status varchar(32) NOT NULL);"
        )
        migrations = [
            "20261116190000_58_kcm_training_lineage_revocation.sql",
            "20261116210000_59_kcm_memory_consent_revocation_hooks.sql",
        ]
        root = Path(__file__).resolve().parents[2]
        for migration in migrations:
            await conn.execute(
                (root / "supabase/migrations" / migration).read_text(
                    encoding="utf-8"
                )
            )

        await conn.execute(
            "INSERT INTO public.tenants(id) VALUES($1),($2)",
            TENANT_A, TENANT_B,
        )
        await conn.execute(
            "INSERT INTO public.auth_users(user_id,tenant_id) "
            "VALUES($1,$2),($3,$4)",
            USER_A, TENANT_A, USER_B, TENANT_B,
        )

        for tenant, user in ((TENANT_A, USER_A), (TENANT_B, USER_B)):
            assert await _scoped(
                conn, tenant, user,
                "SELECT kcm_internal.kcm_provision_training_scope($1,$2)",
                tenant, user,
            ) == 0

        # Memory lifecycle revocation is committed together with validity.
        event_tombstone = uuid.uuid4()
        await _make_source(conn, TENANT_A, USER_A, event_tombstone)
        assert await _source_status(conn, event_tombstone) == "quarantined"
        await conn.execute(
            "UPDATE public.memory_event "
            "SET valid_to=clock_timestamp() WHERE event_id=$1",
            event_tombstone,
        )
        assert await _epoch(conn, TENANT_A, USER_A) == 1
        assert await _source_status(conn, event_tombstone) == "revoked"
        assert await conn.fetchval(
            "SELECT reason_code FROM public.kcm_training_source_revocations "
            "WHERE source_event_id=$1", event_tombstone,
        ) == "memory_tombstoned"
        await conn.execute(
            "UPDATE public.memory_event "
            "SET valid_to=valid_to WHERE event_id=$1", event_tombstone,
        )
        assert await _epoch(conn, TENANT_A, USER_A) == 1

        # A source with changed contents is invalidated even when its claimed
        # hash was incorrectly left unchanged by a legacy writer.
        event_payload = uuid.uuid4()
        await _make_source(conn, TENANT_A, USER_A, event_payload)
        await conn.execute(
            "UPDATE public.memory_event "
            "SET payload='{"+'"revised"'+":true}'::jsonb WHERE event_id=$1",
            event_payload,
        )
        assert await _source_status(conn, event_payload) == "revoked"
        assert await _epoch(conn, TENANT_A, USER_A) == 2

        # Source DELETE also fences ancestry before its commit.
        event_delete = uuid.uuid4()
        await _make_source(conn, TENANT_A, USER_A, event_delete)
        await conn.execute(
            "DELETE FROM public.memory_event WHERE event_id=$1", event_delete,
        )
        assert await _source_status(conn, event_delete) == "revoked"
        assert await _epoch(conn, TENANT_A, USER_A) == 3

        # Supersession invalidates the previous source without requiring a
        # separate UPDATE of its old memory-event row.
        event_old, event_new = uuid.uuid4(), uuid.uuid4()
        await _make_source(conn, TENANT_A, USER_A, event_old)
        await conn.execute(
            "INSERT INTO public.memory_event "
            "(event_id,tenant_id,user_id,payload_hash,event_type,payload,supersedes) "
            "VALUES($1,$2,$3,$4,'memory_persisted','{}'::jsonb,$5)",
            event_new, TENANT_A, USER_A, "d" * 64, event_old,
        )
        assert await _source_status(conn, event_old) == "revoked"
        assert await _epoch(conn, TENANT_A, USER_A) == 4

        # Source from a different owner must remain untouched.
        foreign_event = uuid.uuid4()
        await _make_source(conn, TENANT_B, USER_B, foreign_event)
        assert await _epoch(conn, TENANT_B, USER_B) == 0

        # Consent revocation invalidates every currently quarantined source
        # for that owner. It does not pretend a stale memory consent is rights.
        consent_id = uuid.uuid4()
        await conn.execute(
            "INSERT INTO public.consent_scope"
            "(scope_id,tenant_id,user_id,scope_name,is_granted) "
            "VALUES($1,$2,$3,'private',TRUE)",
            consent_id, TENANT_A, USER_A,
        )
        event_consent_a, event_consent_b = uuid.uuid4(), uuid.uuid4()
        await _make_source(conn, TENANT_A, USER_A, event_consent_a)
        await _make_source(conn, TENANT_A, USER_A, event_consent_b)
        assert await _epoch(conn, TENANT_A, USER_A) == 4
        await conn.execute(
            "UPDATE public.consent_scope SET is_granted=FALSE,"
            "revoked_at=clock_timestamp() WHERE scope_id=$1", consent_id,
        )
        assert await _source_status(conn, event_consent_a) == "revoked"
        assert await _source_status(conn, event_consent_b) == "revoked"
        assert await conn.fetchval(
            "SELECT count(*) FROM public.kcm_training_scope_invalidations "
            "WHERE tenant_id=$1 AND user_id=$2 AND reason_code='consent_revoked'",
            TENANT_A, USER_A,
        ) == 1
        assert await _epoch(conn, TENANT_A, USER_A) == 7
        assert await _epoch(conn, TENANT_B, USER_B) == 0
        assert await _source_status(conn, foreign_event) == "quarantined"

        # A revoked source cannot be reintroduced into another dataset.
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO public.kcm_dataset_source_lineage "
                "(tenant_id,user_id,dataset_id,dataset_version,assessment_id,"
                "source_event_id,source_revision,manifest_sha256,split,"
                "leakage_group_id) "
                "VALUES($1,$2,$3,2,$4,$5,$6,$7,'train','replay')",
                TENANT_A, USER_A, uuid.uuid4(), uuid.uuid4(),
                event_consent_a, REVISION, "b" * 64,
            )

        # Privacy request becoming in-progress fences all current lineage,
        # regardless of when raw memory deletion completes.
        event_privacy = uuid.uuid4()
        await _make_source(conn, TENANT_A, USER_A, event_privacy)
        privacy_id = uuid.uuid4()
        await conn.execute(
            "INSERT INTO public.privacy_requests "
            "(request_id,tenant_id,user_id,request_type,status) "
            "VALUES($1,$2,$3,'erasure','pending')",
            privacy_id, TENANT_A, USER_A,
        )
        assert await _epoch(conn, TENANT_A, USER_A) == 7
        await conn.execute(
            "UPDATE public.privacy_requests SET status='in_progress' "
            "WHERE request_id=$1", privacy_id,
        )
        assert await _source_status(conn, event_privacy) == "revoked"
        assert await conn.fetchval(
            "SELECT count(*) FROM public.kcm_training_scope_invalidations "
            "WHERE tenant_id=$1 AND user_id=$2 "
            "AND reason_code='privacy_erasure'",
            TENANT_A, USER_A,
        ) == 1
        assert await _epoch(conn, TENANT_A, USER_A) == 9

        # Fail-closed atomicity: failure to persist a revocation makes the
        # original memory mutation rollback, not silently succeed.
        event_rollback = uuid.uuid4()
        await _make_source(conn, TENANT_A, USER_A, event_rollback)
        old_epoch = await _epoch(conn, TENANT_A, USER_A)
        with pytest.raises(asyncpg.PostgresError):
            async with conn.transaction():
                await conn.execute(
                    "CREATE FUNCTION kcm_internal.test_refuse_revocation() "
                    "RETURNS trigger LANGUAGE plpgsql AS "
                    "$$BEGIN RAISE EXCEPTION 'synthetic KCM write failure';"
                    "END;$$;"
                    "CREATE TRIGGER kcm_test_refuse_revocation "
                    "BEFORE INSERT ON public.kcm_training_source_revocations "
                    "FOR EACH ROW EXECUTE FUNCTION "
                    "kcm_internal.test_refuse_revocation();"
                )
                await conn.execute(
                    "UPDATE public.memory_event "
                    "SET valid_to=clock_timestamp() WHERE event_id=$1",
                    event_rollback,
                )
        assert await conn.fetchval(
            "SELECT valid_to FROM public.memory_event WHERE event_id=$1",
            event_rollback,
        ) is None
        assert await _source_status(conn, event_rollback) == "quarantined"
        assert await _epoch(conn, TENANT_A, USER_A) == old_epoch
        assert not await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_trigger "
            "WHERE tgname='kcm_test_refuse_revocation')"
        )

        # The scope invalidation table must enforce owner RLS under a genuine
        # non-bypass role even when the caller tries to omit SQL predicates.
        reader_role = f"kcm_lifecycle_reader_{uuid.uuid4().hex[:10]}"
        await conn.execute(f'CREATE ROLE "{reader_role}" NOLOGIN')
        await conn.execute(
            f'GRANT USAGE ON SCHEMA public TO "{reader_role}"'
        )
        await conn.execute(
            f'GRANT SELECT ON public.kcm_training_scope_invalidations '
            f'TO "{reader_role}"'
        )
        for tenant, user, expected in (
            (TENANT_A, USER_A, 2),
            (TENANT_B, USER_B, 0),
            (TENANT_A, USER_B, 0),
        ):
            async with conn.transaction():
                await conn.execute(f'SET LOCAL ROLE "{reader_role}"')
                await conn.execute(
                    "SELECT set_config('app.current_tenant_id',$1,true),"
                    "set_config('app.current_user_id',$2,true)",
                    str(tenant), str(user),
                )
                visible = await conn.fetchval(
                    "SELECT count(*) "
                    "FROM public.kcm_training_scope_invalidations"
                )
                assert visible == expected
        # No derived lineage escapes full canonical user erasure.
        await conn.execute(
            "DELETE FROM public.auth_users WHERE user_id=$1", USER_A,
        )
        for table in (
            "kcm_training_scope_state",
            "kcm_dataset_source_lineage",
            "kcm_training_source_revocations",
            "kcm_training_scope_invalidations",
        ):
            assert await conn.fetchval(
                f"SELECT count(*) FROM public.{table} WHERE user_id=$1",
                USER_A,
            ) == 0

    finally:
        await conn.close()
