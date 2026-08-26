from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.database.models import AuthUser, Base, Tenant
from ai_karen_engine.services.auth.auth_service import AuthService, UserRole
from ai_karen_engine.services.auth.config import AuthConfig, Environment


pytestmark = pytest.mark.asyncio


def _auth_config() -> AuthConfig:
    return AuthConfig(
        environment=Environment.LOCAL,
        jwt_secret_key="first-admin-concurrency-test-secret-32-bytes-minimum",
        bcrypt_rounds=10,
    )


async def test_first_admin_bootstrap_allows_exactly_one_concurrent_winner() -> None:
    """The real PostgreSQL bootstrap lock must permit exactly one first admin.

    The winning bootstrap must also create/resolve exactly one durable tenant and
    bind the first admin to that tenant in the same transaction. A beta release
    must never manufacture a synthetic ``default`` tenant after authentication.
    """

    database_url = os.environ["AUTH_TEST_DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    ordered_tables = [Tenant.__table__, AuthUser.__table__]

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

    async def bootstrap(email: str) -> tuple[str, object]:
        service = AuthService(_auth_config())
        service._initialized = True
        service._tables_ensured = True

        async with session_factory() as db_session:
            async with db_session.begin():
                service.set_db_session(db_session)
                try:
                    user = await service.create_first_admin(
                        email=email,
                        password="BetaLaunch1!",
                        full_name="Beta Launch Admin",
                    )
                    return "created", user
                except ValueError as exc:
                    return "rejected", str(exc)

    first, second = await asyncio.gather(
        bootstrap("first-admin-a@example.test"),
        bootstrap("first-admin-b@example.test"),
    )
    outcomes = [first, second]

    winners = [payload for state, payload in outcomes if state == "created"]
    rejected = [payload for state, payload in outcomes if state == "rejected"]

    assert len(winners) == 1
    assert len(rejected) == 1
    assert "already been completed" in str(rejected[0])

    winner = winners[0]
    winner_roles = {
        role.value if isinstance(role, UserRole) else str(role)
        for role in winner.roles
    }
    assert {"admin", "user"}.issubset(winner_roles)
    assert winner.tenant_id
    assert winner.tenant_id not in {"default", "dev-tenant"}

    async with session_factory() as db_session:
        user_count_result = await db_session.execute(
            select(func.count()).select_from(AuthUser)
        )
        assert user_count_result.scalar_one() == 1

        tenant_count_result = await db_session.execute(
            select(func.count()).select_from(Tenant)
        )
        assert tenant_count_result.scalar_one() == 1

        tenant_result = await db_session.execute(select(Tenant))
        durable_tenant = tenant_result.scalar_one()

        user_result = await db_session.execute(select(AuthUser))
        durable_user = user_result.scalar_one()
        assert "admin" in set(durable_user.roles or [])
        assert "user" in set(durable_user.roles or [])
        assert durable_user.is_active is True
        assert durable_user.is_verified is True
        assert durable_user.tenant_id == durable_tenant.id
        assert winner.tenant_id == str(durable_tenant.id)

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.drop_all(
                sync_connection,
                tables=list(reversed(ordered_tables)),
                checkfirst=True,
            )
        )
    await engine.dispose()
