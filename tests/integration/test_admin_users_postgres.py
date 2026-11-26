"""Real PostgreSQL proof for canonical admin user paging and durable session reads."""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.database.models import AuthSession, AuthUser, Base, Tenant
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
    from ai_karen_engine.database.tenant_manager import TenantConfig, TenantManager

    url = os.environ["AUTH_TEST_DATABASE_URL"]
    engine = create_async_engine(url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tables = [Tenant.__table__, AuthUser.__table__, AuthSession.__table__]
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

        # Duplicate slug, email and username must not leave an orphan tenant.
        with pytest.raises(ValueError):
            await create(slug, f"other-{suffix}@example.test")
        with pytest.raises(ValueError):
            await create(slug + "-email", email)
        with pytest.raises(ValueError):
            await create(slug + "-username", email.replace("@example.test", "@example.org"))
        with pytest.raises(ValueError):
            await create(slug + "-weak", f"weak-{suffix}@example.test", "weak")
        assert await count_tenants() == 1
        async with factory() as session:
            assert await session.scalar(
                select(func.count()).select_from(AuthUser).where(AuthUser.tenant_id == tenant.id)
            ) == 1
        assert not auth._user_cache
    finally:
        # Remove only fixture-owned rows, never any pre-existing account or tenant.
        try:
            async with factory() as session:
                async with session.begin():
                    tenant_ids = select(Tenant.id).where(Tenant.slug.startswith(slug))
                    await session.execute(delete(AuthUser).where(AuthUser.tenant_id.in_(tenant_ids)))
                    await session.execute(delete(Tenant).where(Tenant.slug.startswith(slug)))
        finally:
            await engine.dispose()
