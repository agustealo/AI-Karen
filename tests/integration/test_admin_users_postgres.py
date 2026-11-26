"""Real PostgreSQL proof for canonical admin user paging and durable session reads."""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.database.models import AuditLog, AuthSession, AuthUser, Base, Tenant
from ai_karen_engine.services.auth.auth_service import AuthService, UserRole, UserStatus
from ai_karen_engine.services.auth.config import AuthConfig, Environment


@pytest.mark.asyncio
async def test_admin_pagination_and_sessions_against_postgres():
    url = os.environ["AUTH_TEST_DATABASE_URL"]
    engine = create_async_engine(url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tables = [Tenant.__table__, AuthUser.__table__, AuthSession.__table__]
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    suffix = uuid.uuid4().hex[:10]
    user_ids = [uuid.uuid4() for _ in range(4)]
    config = AuthConfig(
        environment=Environment.LOCAL,
        jwt_secret_key="postgres-admin-proof-secret-at-least-32-bytes",
        bcrypt_rounds=10,
    )
    auth = AuthService(config)
    auth._initialized = True
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_conn: Base.metadata.create_all(
                    sync_conn, tables=tables, checkfirst=True,
                )
            )
        async with factory() as session:
            async with session.begin():
                for tenant, name in [(tenant_a, "a"), (tenant_b, "b")]:
                    session.add(Tenant(
                        id=tenant, name="Proof " + name,
                        slug=f"admin-proof-{name}-{suffix}",
                        subscription_tier="basic", settings={}, is_active=True,
                    ))
                for index, user_id in enumerate(user_ids):
                    session.add(AuthUser(
                        user_id=user_id,
                        email=f"admin-proof-{suffix}-{index}@example.test",
                        username=f"admin-proof-{suffix}-{index}",
                        full_name="Proof Admin" if index < 2 else "Other User",
                        password_hash="not-a-usable-hash",
                        tenant_id=tenant_a if index < 3 else tenant_b,
                        roles=["admin"] if index < 2 else ["user"],
                        preferences={}, is_verified=True, is_active=index != 1,
                    ))
                session.add(AuthSession(
                    session_token=uuid.uuid4(), user_id=user_ids[0],
                    access_token="not-a-real-access-token",
                    refresh_token="not-a-real-refresh-token",
                    expires_in=3600, is_active=True,
                ))

        async with factory() as session:
            auth.set_db_session(session)
            page1, count1 = await auth.list_users_page(
                tenant_id=str(tenant_a), role=UserRole.ADMIN,
                search=f"admin-proof-{suffix}", limit=1, offset=0,
            )
            page2, count2 = await auth.list_users_page(
                tenant_id=str(tenant_a), role=UserRole.ADMIN,
                search=f"admin-proof-{suffix}", limit=1, offset=1,
            )
            assert count1 == count2 == 2
            assert len(page1) == len(page2) == 1
            assert page1[0].id != page2[0].id
            active, active_count = await auth.list_users_page(
                tenant_id=str(tenant_a), status=UserStatus.ACTIVE,
                search=f"admin-proof-{suffix}",
            )
            assert active_count == len(active) == 2
            _, other_count = await auth.list_users_page(
                tenant_id=str(tenant_b), role=UserRole.ADMIN,
                search=f"admin-proof-{suffix}",
            )
            assert other_count == 0
            sessions = await auth.list_sessions(user_id=str(user_ids[0]), strict_errors=True)
            assert len(sessions) == 1
            assert sessions[0]["is_active"] is True
    finally:
        # Cleanup affects only rows seeded by this test, never other users.
        from sqlalchemy import delete
        async with factory() as session:
            async with session.begin():
                await session.execute(delete(AuthSession).where(AuthSession.user_id.in_(user_ids)))
                await session.execute(delete(AuthUser).where(AuthUser.user_id.in_(user_ids)))
                await session.execute(delete(Tenant).where(Tenant.id.in_([tenant_a, tenant_b])))
        await engine.dispose()


@pytest.mark.asyncio
async def test_tenant_and_admin_creation_commit_and_rollback_against_postgres(monkeypatch):
    """Use the same disposable PostgreSQL service as the Admin Users proof."""
    from contextlib import asynccontextmanager
    from sqlalchemy import delete, func, select
    from ai_karen_engine.auth import auth_service
    from ai_karen_engine.database import tenant_manager
    from ai_karen_engine.database.tenant_manager import TenantConfig, TenantManager

    url = os.environ["AUTH_TEST_DATABASE_URL"]
    engine = create_async_engine(url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tables = [Tenant.__table__, AuthUser.__table__, AuthSession.__table__, AuditLog.__table__]
    operator_id = str(uuid.uuid4())
    suffix = uuid.uuid4().hex
    slug = f"tenant-create-proof-{suffix}"
    email = f"tenant-create-proof-{suffix}@example.test"
    password = "ProofPassword1!"
    auth = AuthService(AuthConfig(
        environment=Environment.LOCAL,
        jwt_secret_key="tenant-create-proof-secret-at-least-32-bytes",
        bcrypt_rounds=10,
    ))
    auth._initialized = True

    class Client:
        @asynccontextmanager
        async def get_async_session(self):
            async with factory() as session:
                async with session.begin():
                    yield session

    async def get_auth():
        return auth

    monkeypatch.setattr(auth_service, "get_auth_service", get_auth)
    manager = TenantManager(Client())

    async def create(tenant_slug, admin_email, admin_password=password):
        return await manager.create_tenant(
            TenantConfig("Proof Tenant", tenant_slug), admin_email,
            admin_password=admin_password, admin_full_name="Proof Administrator",
            operator_id=operator_id,
        )

    async def count_tenants():
        async with factory() as session:
            return await session.scalar(
                select(func.count()).select_from(Tenant).where(Tenant.slug.startswith(slug))
            )

    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_conn: Base.metadata.create_all(
                    sync_conn, tables=tables, checkfirst=True,
                )
            )
        tenant = await create(slug, email)
        async with factory() as session:
            admin = (await session.execute(
                select(AuthUser).where(AuthUser.email == email)
            )).scalar_one()
            assert admin.tenant_id == tenant.id
            assert admin.roles == ["admin", "user"]
            assert admin.is_verified and admin.is_active
            assert admin.password_hash != password
            assert auth._verify_password(password, admin.password_hash)
            receipt = (await session.execute(
                select(AuditLog).where(AuditLog.tenant_id == str(tenant.id))
            )).scalar_one()
            assert receipt.user_id == operator_id
            assert receipt.actor_type == "user"
            assert receipt.action == "admin_tenant_create"
            assert receipt.resource_type == "tenant"
            assert receipt.resource_id == str(tenant.id)
            assert receipt.details == {"initial_admin_user_id": str(admin.user_id)}

        # Duplicate slug, email and username must not leave an orphan tenant.
        with pytest.raises(ValueError):
            await create(slug, f"other-{suffix}@example.test")
        with pytest.raises(ValueError):
            await create(slug + "-email", email)
        with pytest.raises(ValueError):
            await create(slug + "-username", email.replace("@example.test", "@example.org"))
        with pytest.raises(ValueError):
            await create(slug + "-weak", f"weak-{suffix}@example.test", "weak")
        # A real database NOT NULL violation on the audit insert must roll
        # back both the new tenant and its newly staged administrator.
        def invalid_receipt(**kwargs):
            return AuditLog(**{**kwargs, "action": None})

        with monkeypatch.context() as patch:
            patch.setattr(tenant_manager, "AuditLog", invalid_receipt)
            with pytest.raises(ValueError):
                await create(slug + "-audit", f"audit-{suffix}@example.test")

        assert await count_tenants() == 1
        async with factory() as session:
            assert await session.scalar(
                select(func.count()).select_from(AuthUser).where(AuthUser.tenant_id == tenant.id)
            ) == 1
            assert await session.scalar(
                select(func.count()).select_from(AuthUser).where(
                    AuthUser.email == f"audit-{suffix}@example.test"
                )
            ) == 0
            assert await session.scalar(
                select(func.count()).select_from(AuditLog).where(AuditLog.user_id == operator_id)
            ) == 1
        assert not auth._user_cache
    finally:
        # Remove only fixture-owned rows, never any pre-existing account or tenant.
        try:
            async with factory() as session:
                async with session.begin():
                    tenant_ids = select(Tenant.id).where(Tenant.slug.startswith(slug))
                    await session.execute(delete(AuditLog).where(AuditLog.user_id == operator_id))
                    await session.execute(delete(AuthUser).where(AuthUser.tenant_id.in_(tenant_ids)))
                    await session.execute(delete(Tenant).where(Tenant.slug.startswith(slug)))
        finally:
            await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("KAREN_TEST_TENANT_CREATION_RLS") != "1",
    reason="Requires explicit disposable migration-backed tenant creation proof",
)
async def test_tenant_creation_under_migrated_non_bypass_role(monkeypatch):
    """Exercise actual migration-owned auth/audit policies and canonical writer."""
    import re
    from contextlib import asynccontextmanager
    from pathlib import Path

    import asyncpg
    from sqlalchemy import func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import DBAPIError
    from ai_karen_engine.auth import auth_service
    from ai_karen_engine.database import tenant_manager
    from ai_karen_engine.database.tenant_manager import TenantConfig, TenantManager
    from ai_karen_engine.persistence.postgres.transactions import (
        apply_authenticated_transaction_context,
    )

    root_url = make_url(os.environ["AUTH_TEST_DATABASE_URL"])
    assert root_url.drivername == "postgresql+asyncpg"
    assert root_url.host in ("127.0.0.1", "localhost")
    assert root_url.port == 5432 and root_url.database == "karen_auth_test"
    assert not root_url.query
    database = "karen_auth_tenant_rls_test"
    role = "karen_auth_tenant_rls_actor"
    url = root_url.set(database=database)
    root = await asyncpg.connect(
        root_url.set(drivername="postgresql").render_as_string(hide_password=False)
    )
    database_created = role_created = False
    engine = None
    operator_tenant, operator = uuid.uuid4(), uuid.uuid4()
    suffix = uuid.uuid4().hex
    slug = f"tenant-rls-{suffix}"
    email = f"tenant-rls-{suffix}@example.test"
    password = "ProofPassword1!"
    config = AuthConfig(
        environment=Environment.LOCAL,
        jwt_secret_key="tenant-rls-proof-secret-at-least-32-bytes",
        bcrypt_rounds=10,
    )
    auth = AuthService(config)
    auth._initialized = True

    async def get_auth():
        return auth

    monkeypatch.setattr(auth_service, "get_auth_service", get_auth)
    try:
        assert not await root.fetchval(
            "SELECT 1 FROM pg_database WHERE datname=$1", database
        ), "Refusing to reuse an existing database"
        assert not await root.fetchval(
            "SELECT 1 FROM pg_roles WHERE rolname=$1", role
        ), "Refusing to reuse an existing role"
        await root.execute(f"CREATE DATABASE {database}")
        database_created = True
        await root.execute(f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS")
        role_created = True
        db = await asyncpg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False)
        )
        try:
            migrations = Path("supabase/migrations")
            baseline = (migrations / "20260827010000_01_core_persona_runtime.sql").read_text()
            finalization = (
                migrations / "20260827050000_05_schema_security_finalization.sql"
            ).read_text()
            # Replay exact source DDL for these tables, not ORM-created tables
            # or synthetic RLS. Unrelated vector/memory schema is out of scope.
            for table in ("auth_users", "audit_log"):
                matches = re.findall(
                    rf"CREATE TABLE {table} \(.*?\n\);", baseline, re.S
                )
                assert len(matches) == 1
                await db.execute(matches[0])
            await db.execute((
                migrations / "20260827020000_02_auth_profile_finalization.sql"
            ).read_text())
            blocks = re.findall(r"DO \$\$.*?END \$\$;", finalization, re.S)
            for table, column in (
                ("auth_users", "tenant_id"),
                ("audit_log", "tenant_id"),
                ("audit_log", "user_id"),
            ):
                matches = [
                    block for block in blocks
                    if f"ALTER TABLE {table}" in block
                    and f"ALTER COLUMN {column} TYPE UUID" in block
                ]
                assert len(matches) == 1
                await db.execute(matches[0])
            await db.execute((
                migrations / "20260916010000_14_auth_tenant_authority.sql"
            ).read_text())
            for table in ("auth_users", "audit_log"):
                enable = f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;"
                assert enable in finalization
                await db.execute(enable)
                matches = re.findall(
                    rf"CREATE POLICY {table}_tenant_isolation ON {table}.*?;",
                    finalization, re.S,
                )
                assert len(matches) == 1
                await db.execute(matches[0])
            await db.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
            await db.execute(f"GRANT SELECT, INSERT ON tenants, auth_users, audit_log TO {role}")
            await db.execute(f"GRANT USAGE ON SEQUENCE audit_log_event_id_seq TO {role}")
            assert tuple(await db.fetchrow(
                "SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname=$1",
                role,
            )) == (False, False, False)
            assert await db.fetchval(
                "SELECT count(*) FROM pg_class WHERE oid IN "
                "('public.auth_users'::regclass, 'public.audit_log'::regclass) "
                "AND relrowsecurity"
            ) == 2
            await db.execute(
                "INSERT INTO tenants(id, name, slug) VALUES($1, 'Operator', 'operator')",
                operator_tenant,
            )
            await db.execute(
                "INSERT INTO auth_users(user_id, tenant_id, email, roles) "
                "VALUES($1, $2, 'operator@example.test', '[\"super_admin\"]'::jsonb)",
                operator, operator_tenant,
            )
        finally:
            await db.close()

        engine = create_async_engine(url, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        @asynccontextmanager
        async def scoped_session(tenant_id):
            async with sessions() as session:
                async with session.begin():
                    await session.execute(text(f"SET LOCAL ROLE {role}"))
                    assert await session.scalar(text("SELECT current_user")) == role
                    assert await session.scalar(text(
                        "SELECT row_security_active('public.auth_users'::regclass) "
                        "AND row_security_active('public.audit_log'::regclass)"
                    ))
                    await apply_authenticated_transaction_context(
                        session, tenant_id=str(tenant_id), user_id=str(operator)
                    )
                    yield session

        class Client:
            def get_async_session(self):
                return scoped_session(operator_tenant)

        manager = TenantManager(Client())

        async def create(name, address, secret=password):
            return await manager.create_tenant(
                TenantConfig("Proof Tenant", name), address,
                admin_password=secret, admin_full_name="Proof Administrator",
                operator_id=str(operator),
            )

        tenant = await create(slug, email)
        tenant_id = tenant.id
        async with scoped_session(tenant_id) as session:
            admin = (await session.execute(select(AuthUser))).scalar_one()
            receipt = (await session.execute(select(AuditLog))).scalar_one()
            assert admin.tenant_id == tenant_id and admin.email == email
            assert admin.roles == ["admin", "user"]
            assert admin.is_verified and admin.is_active
            assert auth._verify_password(password, admin.password_hash)
            assert receipt.user_id == str(operator)
            assert receipt.tenant_id == str(tenant_id)
            assert receipt.action == "admin_tenant_create"
            assert receipt.resource_id == str(tenant_id)
            assert receipt.details == {"initial_admin_user_id": str(admin.user_id)}
            event_id = receipt.event_id

        async with scoped_session(operator_tenant) as session:
            assert (await session.execute(select(AuditLog))).scalars().all() == []
            assert (await session.execute(select(AuthUser.user_id))).scalars().all() == [operator]
        with pytest.raises(DBAPIError) as denied:
            async with scoped_session(operator_tenant) as session:
                session.add(AuditLog(
                    tenant_id=str(tenant_id), user_id=str(operator), action="denied"
                ))
                await session.flush()
        assert denied.value.orig.sqlstate == "42501"

        # RLS hides existing accounts from the new scope; global constraints
        # must still reject email and username collisions across tenants.
        for name, address, secret in (
            (slug, f"other-{suffix}@example.test", password),
            (slug + "-email", email, password),
            (slug + "-username", email.replace("@example.test", "@example.org"), password),
            (slug + "-weak", f"weak-{suffix}@example.test", "weak"),
        ):
            with pytest.raises(ValueError):
                await create(name, address, secret)

        def invalid_receipt(**kwargs):
            return AuditLog(**{**kwargs, "action": None})

        with monkeypatch.context() as patch:
            patch.setattr(tenant_manager, "AuditLog", invalid_receipt)
            with pytest.raises(ValueError):
                await create(slug + "-audit", f"audit-{suffix}@example.test")
        # Privileged inspection is only for whole-database rollback evidence,
        # not for exercising the protected runtime writes above.
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Tenant)) == 2
            assert await session.scalar(select(func.count()).select_from(AuthUser)) == 2
            assert await session.scalar(select(func.count()).select_from(AuditLog)) == 1
        assert not auth._user_cache

        # Recreate the engine and service to rule out in-memory receipt state.
        await engine.dispose()
        engine = create_async_engine(url, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        manager = TenantManager(Client())
        assert await manager.get_tenant(tenant_id) is not None
        async with scoped_session(tenant_id) as session:
            receipt = await session.get(AuditLog, event_id)
            assert receipt is not None and receipt.user_id == str(operator)
    finally:
        try:
            if engine is not None:
                await engine.dispose()
            if database_created:
                await root.execute(f"DROP DATABASE {database}")
            if role_created:
                await root.execute(f"DROP ROLE {role}")
        finally:
            await root.close()
