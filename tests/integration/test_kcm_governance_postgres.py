"""Real PostgreSQL proof for KCM's nonauthorizing lineage and revocation ledger.

Destructive setup is permitted ONLY in a brand-new dedicated karen_kcm_test
database, never in the application's production or shared test databases.
No training authority or training worker is enabled by this test.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest

pytestmark = pytest.mark.asyncio


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


async def _as_principal(
    conn: asyncpg.Connection,
    *,
    tenant: uuid.UUID,
    user: uuid.UUID,
    statement: str,
    args: tuple[object, ...] = (),
) -> object:
    async with conn.transaction():
        await conn.execute(
            "SELECT set_config('app.current_tenant_id', $1, true), "
            "set_config('app.current_user_id', $2, true)",
            str(tenant), str(user),
        )
        return await conn.fetchval(statement, *args)


async def test_real_kcm_rls_revocation_concurrency_and_erasure() -> None:
    dsn = os.getenv("KCM_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Dedicated KCM_TEST_DATABASE_URL not configured")
    if urlparse(dsn).path != "/karen_kcm_test":
        pytest.fail("KCM governance test requires /karen_kcm_test only")

    pg_dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncpg.connect(pg_dsn)
    tenant_a, tenant_b = _uuid(), _uuid()
    user_a, user_b, user_c = _uuid(), _uuid(), _uuid()
    source_a, source_b, source_c = _uuid(), _uuid(), _uuid()
    dataset = _uuid()
    source_hash = "a" * 64
    reader_role = f"kcm_reader_{uuid.uuid4().hex[:10]}"
    second: asyncpg.Connection | None = None
    try:
        await conn.execute(
            "CREATE TABLE public.tenants(id uuid PRIMARY KEY);"
            "CREATE TABLE public.auth_users("
            "user_id uuid PRIMARY KEY, tenant_id uuid NOT NULL);"
        )
        migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/"
            "20261116190000_58_kcm_training_lineage_revocation.sql"
        ).read_text(encoding="utf-8")
        await conn.execute(migration)

        await conn.execute(
            "INSERT INTO public.tenants(id) VALUES($1),($2)",
            tenant_a, tenant_b,
        )
        await conn.execute(
            "INSERT INTO public.auth_users(user_id, tenant_id) "
            "VALUES($1,$2),($3,$4),($5,$6)",
            user_a, tenant_a, user_b, tenant_b, user_c, tenant_a,
        )

        # The canonical private function can provision but never authorize
        # training, even under the migration owner.
        async def provision(tenant: uuid.UUID, user: uuid.UUID) -> int:
            value = await _as_principal(
                conn, tenant=tenant, user=user,
                statement=(
                    "SELECT kcm_internal.kcm_provision_training_scope($1,$2)"
                ), args=(tenant, user),
            )
            assert isinstance(value, int)
            return value

        assert await provision(tenant_a, user_a) == 0
        assert await provision(tenant_b, user_b) == 0
        assert await provision(tenant_a, user_c) == 0

        # Even a privileged caller with matching transaction parameters
        # cannot manufacture a cross-tenant user membership.
        with pytest.raises(asyncpg.CheckViolationError):
            await provision(tenant_a, user_b)
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO public.kcm_training_scope_state "
                "(tenant_id,user_id) VALUES($1,$2)",
                tenant_b, user_a,
            )

        blocked = await conn.fetchval(
            "SELECT training_authorized FROM public.kcm_training_scope_state "
            "WHERE tenant_id=$1 AND user_id=$2",
            tenant_a, user_a,
        )
        assert blocked is False

        with pytest.raises(asyncpg.PostgresError) as err:
            await _as_principal(
                conn, tenant=tenant_a, user=user_c,
                statement=(
                    "SELECT kcm_internal.kcm_provision_training_scope($1,$2)"
                ), args=(tenant_a, user_a),
            )
        assert err.value.sqlstate == "42501"

        await conn.execute(
            "INSERT INTO public.kcm_dataset_source_lineage "
            "(tenant_id, user_id, dataset_id, dataset_version, "
            "assessment_id, source_event_id, source_revision, "
            "manifest_sha256, split, leakage_group_id) "
            "VALUES ($1,$2,$3,1,$4,$5,$6,$7,'train','case-1')",
            tenant_a, user_a, dataset, _uuid(), source_a, source_hash,
            "b" * 64,
        )

        assert await conn.fetchval(
            "SELECT training_authorized FROM public.kcm_dataset_source_lineage "
            "WHERE source_event_id=$1", source_a,
        ) is False
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO public.kcm_dataset_source_lineage "
                "(tenant_id,user_id,dataset_id,dataset_version,assessment_id,"
                "source_event_id,source_revision,manifest_sha256,split,"
                "leakage_group_id,training_authorized) "
                "VALUES ($1,$2,$3,1,$4,$5,$6,$7,'train','case-x',true)",
                tenant_a, user_a, dataset, _uuid(), _uuid(), source_hash,
                "b" * 64,
            )

        # A least-privilege test role verifies real FORCE RLS, not a mocked
        # session or an application-side tenant predicate.
        await conn.execute(f'CREATE ROLE "{reader_role}" NOLOGIN')
        await conn.execute(
            f'GRANT USAGE ON SCHEMA public TO "{reader_role}"'
        )
        await conn.execute(
            'GRANT SELECT ON public.kcm_training_scope_state, '
            'public.kcm_dataset_source_lineage, '
            'public.kcm_training_source_revocations '
            f'TO "{reader_role}"'
        )

        async def visible(
            tenant: uuid.UUID, user: uuid.UUID,
        ) -> tuple[int, int]:
            async with conn.transaction():
                await conn.execute(f'SET LOCAL ROLE "{reader_role}"')
                await conn.execute(
                    "SELECT set_config('app.current_tenant_id',$1,true),"
                    "set_config('app.current_user_id',$2,true)",
                    str(tenant), str(user),
                )
                scopes = await conn.fetchval(
                    "SELECT count(*) FROM public.kcm_training_scope_state"
                )
                lineage = await conn.fetchval(
                    "SELECT count(*) FROM public.kcm_dataset_source_lineage"
                )
                return scopes, lineage

        assert await visible(tenant_a, user_a) == (1, 1)
        assert await visible(tenant_b, user_b) == (1, 0)
        assert await visible(tenant_a, user_c) == (1, 0)
        assert await visible(tenant_b, user_a) == (0, 0)

        with pytest.raises(asyncpg.PostgresError):
            async with conn.transaction():
                await conn.execute(f'SET LOCAL ROLE "{reader_role}"')
                await conn.execute(
                    "SELECT set_config('app.current_tenant_id',$1,true),"
                    "set_config('app.current_user_id',$2,true)",
                    str(tenant_a), str(user_a),
                )
                await conn.fetchval(
                    "SELECT kcm_internal.kcm_revoke_training_source("
                    "$1,$2,$3,$4,$5)",
                    tenant_a, user_a, source_a, source_hash,
                    "memory_deleted",
                )

        async def revoke(
            connection: asyncpg.Connection,
            source: uuid.UUID,
        ) -> int:
            v = await _as_principal(
                connection, tenant=tenant_a, user=user_a,
                statement=(
                    "SELECT kcm_internal.kcm_revoke_training_source("
                    "$1,$2,$3,$4,$5)"
                ),
                args=(tenant_a, user_a, source, source_hash,
                      "memory_deleted"),
            )
            assert isinstance(v, int)
            return v

        assert await revoke(conn, source_a) == 1
        assert await revoke(conn, source_a) == 1
        assert await conn.fetchval(
            "SELECT deletion_epoch FROM public.kcm_training_scope_state "
            "WHERE tenant_id=$1 AND user_id=$2",
            tenant_a, user_a,
        ) == 1
        row = await conn.fetchrow(
            "SELECT lineage_status,revoked_at "
            "FROM public.kcm_dataset_source_lineage WHERE source_event_id=$1",
            source_a,
        )
        assert row["lineage_status"] == "revoked"
        assert row["revoked_at"] is not None

        # A source cannot be resurrected into a new dataset version after
        # an already committed revocation.
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO public.kcm_dataset_source_lineage "
                "(tenant_id,user_id,dataset_id,dataset_version,assessment_id,"
                "source_event_id,source_revision,manifest_sha256,split,"
                "leakage_group_id) "
                "VALUES($1,$2,$3,2,$4,$5,$6,$7,'train','replay')",
                tenant_a, user_a, dataset, _uuid(), source_a,
                source_hash, "b" * 64,
            )

        # Concurrent different-source revocations must serialize on the
        # same scope row and produce two distinct monotonic epochs.
        second = await asyncpg.connect(pg_dsn)
        epochs = await asyncio.gather(
            revoke(conn, source_b),
            revoke(second, source_c),
        )
        assert sorted(epochs) == [2, 3]
        assert await conn.fetchval(
            "SELECT deletion_epoch FROM public.kcm_training_scope_state "
            "WHERE tenant_id=$1 AND user_id=$2",
            tenant_a, user_a,
        ) == 3
        assert await conn.fetchval(
            "SELECT count(*) FROM public.kcm_training_source_revocations "
            "WHERE tenant_id=$1 AND user_id=$2",
            tenant_a, user_a,
        ) == 3

        # User erasure must remove every derived KCM record, not retain a
        # hidden secondary copy of personal source relationships.
        await conn.execute(
            "DELETE FROM public.auth_users WHERE user_id=$1", user_a,
        )
        for table in (
            "kcm_training_scope_state",
            "kcm_dataset_source_lineage",
            "kcm_training_source_revocations",
        ):
            assert await conn.fetchval(
                f"SELECT count(*) FROM public.{table} WHERE user_id=$1",
                user_a,
            ) == 0

        assert await visible(tenant_b, user_b) == (1, 0)
    finally:
        if second is not None:
            await second.close()
        if not conn.is_closed():
            await conn.close()
