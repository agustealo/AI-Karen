"""Real PostgreSQL proof for governed plugin settings.

Uses only a disposable database whose path is exactly
/karen_plugin_settings_test. The actual migration is applied, and repository
queries run under a non-superuser role so FORCE RLS is truly exercised.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.services.plugin_settings_repository import (
    PluginSettingsRepository,
    PluginSettingsRevisionConflict,
)


@pytest.mark.asyncio
async def test_live_plugin_settings_tenant_rls_cas_and_audit_atomicity():
    dsn = os.getenv("PLUGIN_SETTINGS_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("A dedicated plugin settings PostgreSQL test database is not configured")
    if urlparse(dsn).path != "/karen_plugin_settings_test":
        pytest.fail("Plugin settings proof requires /karen_plugin_settings_test")

    raw = await asyncpg.connect(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    engine = None
    role = "plugin_settings_test_" + uuid.uuid4().hex[:12]
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    try:
        await raw.execute("""
            DROP TABLE IF EXISTS public.extension_plugin_settings_audit CASCADE;
            DROP TABLE IF EXISTS public.extension_plugin_settings CASCADE;
            CREATE TABLE IF NOT EXISTS public.tenants (id uuid PRIMARY KEY);
        """)
        migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261114030000_51_tenant_plugin_settings.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(migration)
        await raw.execute(
            "INSERT INTO public.tenants(id) VALUES($1),($2) ON CONFLICT DO NOTHING",
            tenant_a, tenant_b,
        )
        await raw.execute(f'CREATE ROLE "{role}" NOLOGIN')
        await raw.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
        await raw.execute(
            f'GRANT SELECT, INSERT, UPDATE ON public.extension_plugin_settings TO "{role}"'
        )
        await raw.execute(
            f'GRANT SELECT, INSERT ON public.extension_plugin_settings_audit TO "{role}"'
        )
        await raw.execute(
            f'GRANT USAGE ON SEQUENCE public.extension_plugin_settings_audit_id_seq TO "{role}"'
        )

        url = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(url, pool_size=4, max_overflow=0)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        class ScopedTestClient:
            @asynccontextmanager
            async def get_async_session(self):
                async with factory() as session:
                    async with session.begin():
                        # Connection user is postgres. SET LOCAL ROLE makes this
                        # test subject to actual tenant RLS as a non-superuser.
                        await session.execute(text(f'SET LOCAL ROLE "{role}"'))
                        yield session

        repo = PluginSettingsRepository(lambda: ScopedTestClient())

        def args(tenant, settings, revision, plugin_id="settings-test"):
            return {
                "tenant_id": str(tenant),
                "plugin_id": plugin_id,
                "actor_user_id": "operator-1",
                "operation": "save",
                "settings": settings,
                "expected_revision": revision,
                "request_id": "request-1",
                "correlation_id": "corr-1",
            }

        assert await repo.write(**args(tenant_a, {"region": "east"}, 0)) == 1
        assert await repo.get(str(tenant_a), "settings-test") == {
            "settings": {"region": "east"}, "revision": 1,
        }
        assert await repo.get(str(tenant_b), "settings-test") == {
            "settings": {}, "revision": 0,
        }
        assert await repo.write(**args(tenant_b, {"region": "west"}, 0)) == 1

        # The same arbitrary SELECT under tenant A must not see tenant B.
        async with ScopedTestClient().get_async_session() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                {"tenant": str(tenant_a)},
            )
            hidden = await session.execute(
                text(
                    "SELECT plugin_id FROM public.extension_plugin_settings "
                    "WHERE tenant_id = CAST(:tenant AS uuid)"
                ),
                {"tenant": str(tenant_b)},
            )
            assert hidden.scalars().all() == []

        # Two concurrent writers saw revision 1. Exactly one can win.
        results = await asyncio.gather(
            repo.write(**args(tenant_a, {"region": "north"}, 1)),
            repo.write(**args(tenant_a, {"region": "south"}, 1)),
            return_exceptions=True,
        )
        assert len([value for value in results if value == 2]) == 1
        assert len([
            value for value in results
            if isinstance(value, PluginSettingsRevisionConflict)
        ]) == 1
        assert (await repo.get(str(tenant_a), "settings-test"))["revision"] == 2

        # An audit insert denial must roll back the *same* settings mutation.
        await raw.execute(
            f'REVOKE INSERT ON public.extension_plugin_settings_audit FROM "{role}"'
        )
        with pytest.raises(Exception, match="permission denied"):
            await repo.write(**args(tenant_a, {"region": "never-persist"}, 2))
        await raw.execute(
            f'GRANT INSERT ON public.extension_plugin_settings_audit TO "{role}"'
        )
        current = await repo.get(str(tenant_a), "settings-test")
        assert current["revision"] == 2
        assert current["settings"]["region"] != "never-persist"

        # Value-free audit table reports only successful durable revisions.
        async with ScopedTestClient().get_async_session() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                {"tenant": str(tenant_a)},
            )
            events = await session.execute(
                text(
                    "SELECT revision, operation, actor_user_id "
                    "FROM public.extension_plugin_settings_audit "
                    "WHERE tenant_id = CAST(:tenant AS uuid) ORDER BY revision"
                ),
                {"tenant": str(tenant_a)},
            )
            rows = events.mappings().all()
            assert [(row["revision"], row["operation"]) for row in rows] == [
                (1, "save"), (2, "save"),
            ]
            assert {row["actor_user_id"] for row in rows} == {"operator-1"}
    finally:
        if engine is not None:
            await engine.dispose()
        # Dedicated disposable database, but clean the role rather than leak
        # a cluster-global test principal into another test.
        try:
            await raw.execute(f'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "{role}"')
            await raw.execute(f'REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM "{role}"')
            await raw.execute(f'REVOKE USAGE ON SCHEMA public FROM "{role}"')
            await raw.execute(f'DROP ROLE IF EXISTS "{role}"')
        finally:
            await raw.close()
