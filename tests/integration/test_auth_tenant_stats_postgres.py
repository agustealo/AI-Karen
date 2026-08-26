from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.database.models import AuthSession, AuthUser, Base, Tenant
from ai_karen_engine.services.auth.auth_service import AuthService
from ai_karen_engine.services.auth.config import AuthConfig, Environment


pytestmark = pytest.mark.asyncio


def _config() -> AuthConfig:
    return AuthConfig(
        environment=Environment.LOCAL,
        jwt_secret_key="tenant-stats-test-secret-32-bytes-minimum",
        bcrypt_rounds=10,
    )


async def test_auth_stats_are_isolated_by_tenant_in_postgres() -> None:
    database_url = os.environ["AUTH_TEST_DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ordered_tables = [Tenant.__table__, AuthUser.__table__, AuthSession.__table__]

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.drop_all(
                sync_connection,
                tables=list(reversed(ordered_tables)),
                checkfirst=True,
            )
        )
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=ordered_tables,
                checkfirst=True,
            )
        )

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    service = AuthService(_config())
    service._initialized = True

    async with session_factory() as db_session:
        async with db_session.begin():
            db_session.add_all(
                [
                    Tenant(id=tenant_a, name="Tenant A", slug="tenant-a"),
                    Tenant(id=tenant_b, name="Tenant B", slug="tenant-b"),
                    AuthUser(
                        user_id=user_a,
                        email="a@example.test",
                        username="tenant-a-user",
                        full_name="Tenant A User",
                        password_hash=service._hash_password("Original1!"),
                        tenant_id=tenant_a,
                        roles=["admin"],
                        preferences={},
                        is_verified=True,
                        is_active=True,
                    ),
                    AuthUser(
                        user_id=user_b,
                        email="b@example.test",
                        username="tenant-b-user",
                        full_name="Tenant B User",
                        password_hash=service._hash_password("Original1!"),
                        tenant_id=tenant_b,
                        roles=["admin"],
                        preferences={},
                        is_verified=True,
                        is_active=True,
                    ),
                    AuthSession(
                        session_token=uuid.uuid4(),
                        user_id=user_a,
                        access_token="access-a",
                        refresh_token="refresh-a",
                        expires_in=3600,
                        is_active=True,
                    ),
                    AuthSession(
                        session_token=uuid.uuid4(),
                        user_id=user_b,
                        access_token="access-b",
                        refresh_token="refresh-b",
                        expires_in=3600,
                        is_active=True,
                    ),
                ]
            )

    async with session_factory() as db_session:
        async with db_session.begin():
            service.set_db_session(db_session)
            stats_a = await service.get_auth_stats(tenant_id=str(tenant_a))

    assert stats_a["service_status"] == "running"
    assert stats_a["tenant_id"] == str(tenant_a)
    assert stats_a["total_users"] == 1
    assert stats_a["active_users"] == 1
    assert stats_a["total_sessions"] == 1
    assert stats_a["active_sessions"] == 1

    async with session_factory() as db_session:
        async with db_session.begin():
            service.set_db_session(db_session)
            global_stats = await service.get_auth_stats()

    assert global_stats["total_users"] == 2
    assert global_stats["total_sessions"] == 2

    await engine.dispose()
