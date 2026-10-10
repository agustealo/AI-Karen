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
