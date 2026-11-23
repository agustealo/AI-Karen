"""KGUI-CARD-STUDIO-01B: observable PostgreSQL Card Studio acceptance.

Runs only on the disposable karen_card_studio_test database. Executes the
actual migration and canonical repository against a non-owner, RLS-constrained
database login; never points test mutations at an application database.
No API, browser, publication, or model authorization is simulated here.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.persistence.postgres import transactions
from ai_karen_engine.persistence.repositories.card_studio_template_repository import (
    CardStudioTemplateRepository,
    CardTemplateConflict,
    CardTemplateUnavailable,
)

pytestmark = pytest.mark.asyncio

_DATABASE = "karen_card_studio_test"
_APP_ROLE = "karen_ci_card_runtime"
_APP_PASSWORD = "card_studio_ci_only"
_TABLES = (
    "card_studio_templates",
    "card_studio_template_revisions",
    "card_studio_template_mutation_receipts",
)


def _draft(title: str = "Observed clock", key: str = "personal-clock") -> dict:
    return {
        "schema_version": 1,
        "template_key": key,
        "title": title,
        "layout": "stack",
        "density": "comfortable",
        "interaction_mode": "read_only",
        "slots": [{"slot_id": "main", "component_type": "time.observation"}],
    }


def _require_disposable_url() -> str:
    if (
        os.getenv("KAREN_TEST_CARD_STUDIO_POSTGRES") != "1"
        or os.getenv("KAREN_TEST_DISPOSABLE_DATABASE") != "1"
    ):
        pytest.skip("Requires explicitly approved disposable Card Studio PostgreSQL")
    dsn = os.getenv("KAREN_TEST_CARD_STUDIO_DATABASE_URL", "")
    parsed = urlparse(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    if (
        parsed.scheme != "postgresql"
        or parsed.path != f"/{_DATABASE}"
        or parsed.hostname not in ("localhost", "127.0.0.1")
        or parsed.username != "postgres"
    ):
        pytest.fail("Refusing PostgreSQL proof outside the canonical disposable test DB")
    return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _rls_query(conn, tenant: uuid.UUID | None, user: uuid.UUID | None, query: str, *args):
    """Execute one operation with transaction-local principal context."""
    async with conn.transaction():
        if tenant is not None:
            await conn.execute(
                "SELECT set_config('app.current_tenant_id', $1, true)", str(tenant)
            )
        if user is not None:
            await conn.execute(
                "SELECT set_config('app.current_user_id', $1, true)", str(user)
            )
        return await conn.fetch(query, *args)


async def test_real_postgres_card_studio_migration_rls_cas_retries_and_rollback(
    monkeypatch,
) -> None:
    dsn = _require_disposable_url()
    admin = await asyncpg.connect(dsn)
    engine = None
    reader = None
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    owner_a, owner_b, owner_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    repo = CardStudioTemplateRepository()
    migration = (
        Path(__file__).resolve().parents[2]
        / "supabase/migrations/20261122235900_67_card_studio_template_drafts.sql"
    ).read_text(encoding="utf-8")

    try:
        existing = await admin.fetchval("""
            SELECT count(*) FROM information_schema.tables
            WHERE table_schema='public'
              AND table_name IN (
                  'tenants', 'auth_users', 'card_studio_templates',
                  'card_studio_template_revisions',
                  'card_studio_template_mutation_receipts'
              )
        """)
        if existing:
            pytest.fail("Card Studio proof refuses a prepopulated database")

        # The independent foreign-key targets exist only in the disposable DB.
        await admin.execute("""
            CREATE TABLE public.tenants (id UUID PRIMARY KEY);
            CREATE TABLE public.auth_users (user_id UUID PRIMARY KEY);
        """)

        # A mid-migration SQL error must roll back the already-created head.
        broken = migration.replace(
            "CREATE TABLE public.card_studio_template_revisions (",
            "SELECT 1 / 0;\\nCREATE TABLE public.card_studio_template_revisions (",
            1,
        )
        assert broken != migration
        with pytest.raises(asyncpg.PostgresError):
            await admin.execute(broken)
        await admin.execute("ROLLBACK")
        for table in _TABLES:
            assert await admin.fetchval(
                "SELECT to_regclass($1) IS NULL", f"public.{table}"
            ), f"Migration failure left partial table: {table}"

        # Apply exactly the committed production migration, including RLS,
        # immutable-history triggers, client revokes and FKs.
        await admin.execute(migration)
        for table in _TABLES:
            state = await admin.fetchrow("""
                SELECT relrowsecurity, relforcerowsecurity
                FROM pg_class WHERE oid=to_regclass($1)
            """, f"public.{table}")
            assert state["relrowsecurity"] and state["relforcerowsecurity"], table
            for role in ("anon", "authenticated"):
                assert not await admin.fetchval(
                    "SELECT has_table_privilege($1,$2,'SELECT')",
                    role, f"public.{table}",
                )

        await admin.execute(
            "INSERT INTO public.tenants(id) VALUES ($1),($2)", tenant_a, tenant_b
        )
        await admin.execute(
            "INSERT INTO public.auth_users(user_id) VALUES ($1),($2),($3)",
            owner_a, owner_b, owner_c,
        )

        # A real LOGIN role has explicit backend grants, but is neither
        # superuser, table owner, nor BYPASSRLS. No Supabase client grant.
        await admin.execute(
            f"CREATE ROLE {_APP_ROLE} LOGIN PASSWORD '{_APP_PASSWORD}'"
        )
        await admin.execute(f"GRANT USAGE ON SCHEMA public TO {_APP_ROLE}")
        for table in _TABLES:
            await admin.execute(
                f"GRANT SELECT,INSERT,UPDATE,DELETE ON public.{table} TO {_APP_ROLE}"
            )
        assert not await admin.fetchval(
            "SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname=$1",
            _APP_ROLE,
        )

        app_dsn = (
            f"postgresql://{_APP_ROLE}:{_APP_PASSWORD}"
            f"@127.0.0.1:5432/{_DATABASE}"
        )
        reader = await asyncpg.connect(app_dsn)
        engine = create_async_engine(
            app_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
        )
        maker = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(
            transactions,
            "get_postgres_engine",
            lambda: SimpleNamespace(async_session_factory=maker),
        )

        # Absent user/tenant settings must not expose anything.
        assert (await _rls_query(
            reader, None, None,
            "SELECT count(*) AS total FROM public.card_studio_templates",
        ))[0]["total"] == 0

        original_key = str(uuid.uuid4())
        first, first_receipt = await repo.create_draft(
            authenticated_tenant_id=str(tenant_a),
            authenticated_user_id=str(owner_a),
            draft=_draft(),
            idempotency_key=original_key,
        )
        assert first.revision == 1 and first_receipt.revision == 1

        # Connection and repository instance do not control replay identity.
        repeated, repeat_receipt = await CardStudioTemplateRepository().create_draft(
            authenticated_tenant_id=str(tenant_a),
            authenticated_user_id=str(owner_a),
            draft=_draft(),
            idempotency_key=original_key,
        )
        assert (repeated, repeat_receipt) == (first, first_receipt)
        with pytest.raises(CardTemplateConflict, match="Idempotency"):
            await repo.create_draft(
                authenticated_tenant_id=str(tenant_a),
                authenticated_user_id=str(owner_a),
                draft=_draft(title="Altered retry"),
                idempotency_key=original_key,
            )

        # A simultaneous identical create must commit one snapshot/receipt.
        shared_key = str(uuid.uuid4())
        concurrent = await asyncio.wait_for(asyncio.gather(*(
            repo.create_draft(
                authenticated_tenant_id=str(tenant_a),
                authenticated_user_id=str(owner_a),
                draft=_draft(key="parallel-clock"),
                idempotency_key=shared_key,
            )
            for _ in range(2)
        )), timeout=30)
        assert concurrent[0] == concurrent[1]

        # Contending expected_revision=1 edits: exactly one wins.
        revisions = await asyncio.wait_for(
            asyncio.gather(*(
                repo.revise_draft(
                    authenticated_tenant_id=str(tenant_a),
                    authenticated_user_id=str(owner_a),
                    template_id=first.template_id,
                    expected_revision=1,
                    draft=_draft(title=f"Competing revision {i}"),
                    idempotency_key=str(uuid.uuid4()),
                )
                for i in range(2)
            ), return_exceptions=True),
            timeout=30,
        )
        winners = [r for r in revisions if not isinstance(r, BaseException)]
        failures = [r for r in revisions if isinstance(r, BaseException)]
        assert len(winners) == 1 and len(failures) == 1, revisions
        assert isinstance(failures[0], CardTemplateConflict)
        winner, receipt = winners[0]
        assert winner.revision == receipt.revision == 2
        assert [r.revision for r in await repo.list_revisions(
            authenticated_tenant_id=str(tenant_a),
            authenticated_user_id=str(owner_a),
            template_id=first.template_id,
        )] == [2, 1]

        # Real RLS applies to both same-tenant different-user and cross-tenant.
        for denied_tenant, denied_user in (
            (tenant_a, owner_b),
            (tenant_b, owner_c),
        ):
            assert not await repo.list_owned(
                authenticated_tenant_id=str(denied_tenant),
                authenticated_user_id=str(denied_user),
                include_archived=True,
            )
            with pytest.raises(CardTemplateUnavailable):
                await repo.read_owned(
                    authenticated_tenant_id=str(denied_tenant),
                    authenticated_user_id=str(denied_user),
                    template_id=first.template_id,
                )
            with pytest.raises(CardTemplateConflict):
                await repo.revise_draft(
                    authenticated_tenant_id=str(denied_tenant),
                    authenticated_user_id=str(denied_user),
                    template_id=first.template_id,
                    expected_revision=2,
                    draft=_draft(),
                    idempotency_key=str(uuid.uuid4()),
                )
            for table in _TABLES:
                assert not await _rls_query(
                    reader, denied_tenant, denied_user,
                    f"SELECT template_id FROM public.{table} WHERE template_id=$1",
                    uuid.UUID(first.template_id),
                )

        with pytest.raises(asyncpg.PostgresError):
            await _rls_query(
                reader, tenant_b, owner_c,
                "INSERT INTO public.card_studio_templates "
                "(tenant_id,user_id,template_key) VALUES ($1,$2,'forged-clock')",
                tenant_a, owner_a,
            )

        # SQL-level immutability stands even when the restricted role has
        # direct UPDATE/DELETE grants; archive is the only ordinary removal.
        for table, mutation in (
            (
                "card_studio_template_revisions",
                "UPDATE public.card_studio_template_revisions "
                "SET definition='{}'::jsonb WHERE template_id=$1",
            ),
            (
                "card_studio_template_mutation_receipts",
                "DELETE FROM public.card_studio_template_mutation_receipts "
                "WHERE template_id=$1",
            ),
            (
                "card_studio_templates",
                "DELETE FROM public.card_studio_templates "
                "WHERE template_id=$1",
            ),
        ):
            with pytest.raises(asyncpg.PostgresError):
                await _rls_query(
                    reader, tenant_a, owner_a, mutation, uuid.UUID(first.template_id)
                )

        # A failing duplicate receipt INSERT must revert an earlier head
        # revision mutation in the same real transaction.
        with pytest.raises(asyncpg.UniqueViolationError):
            async with reader.transaction():
                await reader.execute(
                    "SELECT set_config('app.current_tenant_id',$1,true)",
                    str(tenant_a),
                )
                await reader.execute(
                    "SELECT set_config('app.current_user_id',$1,true)",
                    str(owner_a),
                )
                await reader.execute(
                    "UPDATE public.card_studio_templates "
                    "SET head_revision=head_revision+1 WHERE template_id=$1",
                    uuid.UUID(first.template_id),
                )
                await reader.execute("""
                    INSERT INTO public.card_studio_template_mutation_receipts
                        (tenant_id,user_id,idempotency_key,operation,
                         request_digest,template_id,committed_revision,
                         result_snapshot)
                    VALUES ($1,$2,$3,'create',$4,$5,2,'{}'::jsonb)
                """, tenant_a, owner_a, uuid.UUID(original_key),
                    "a" * 64, uuid.UUID(first.template_id))

        assert (await repo.read_owned(
            authenticated_tenant_id=str(tenant_a),
            authenticated_user_id=str(owner_a),
            template_id=first.template_id,
        )).revision == 2

        archive_key = str(uuid.uuid4())
        archived, archive_receipt = await repo.archive_draft(
            authenticated_tenant_id=str(tenant_a),
            authenticated_user_id=str(owner_a),
            template_id=first.template_id,
            expected_revision=2,
            idempotency_key=archive_key,
        )
        assert archived.lifecycle == "archived"
        assert archive_receipt.revision == 2
        assert (archived, archive_receipt) == await repo.archive_draft(
            authenticated_tenant_id=str(tenant_a),
            authenticated_user_id=str(owner_a),
            template_id=first.template_id,
            expected_revision=2,
            idempotency_key=archive_key,
        )
        active = await repo.list_owned(
            authenticated_tenant_id=str(tenant_a),
            authenticated_user_id=str(owner_a),
        )
        assert len(active) == 1
        assert active[0].template_id == concurrent[0][0].template_id
        historical = await repo.read_owned(
            authenticated_tenant_id=str(tenant_a),
            authenticated_user_id=str(owner_a),
            template_id=first.template_id,
            revision=1,
        )
        assert historical.revision == 1 and historical.definition == _draft()

        counts = await _rls_query(
            reader, tenant_a, owner_a, """
            SELECT
                (SELECT count(*) FROM public.card_studio_templates) AS heads,
                (SELECT count(*) FROM public.card_studio_template_revisions)
                    AS revisions,
                (SELECT count(*) FROM public.card_studio_template_mutation_receipts)
                    AS receipts
            """,
        )
        assert counts[0]["heads"] == 2
        assert counts[0]["revisions"] == 3
        assert counts[0]["receipts"] == 4

        # Authorized parent erasure must preserve GDPR/tenant deletion path.
        await admin.execute("DELETE FROM public.tenants WHERE id=$1", tenant_a)
        for table in _TABLES:
            assert await admin.fetchval(
                f"SELECT count(*) FROM public.{table} WHERE tenant_id=$1",
                tenant_a,
            ) == 0
    finally:
        if reader is not None:
            await reader.close()
        if engine is not None:
            await engine.dispose()
        await admin.close()
