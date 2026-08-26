from __future__ import annotations

import asyncio
import hashlib
import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.database.models import AuthSession, AuthUser, Base, Tenant
from ai_karen_engine.database.models.session_security import AuthRefreshTokenHistory
from ai_karen_engine.services.auth.auth_service import AuthService
from ai_karen_engine.services.auth.config import AuthConfig, Environment


pytestmark = pytest.mark.asyncio


def _auth_config() -> AuthConfig:
    return AuthConfig(
        environment=Environment.LOCAL,
        jwt_secret_key="postgres-concurrency-test-secret-32-bytes-minimum",
        bcrypt_rounds=10,
    )


async def test_same_refresh_token_concurrency_allows_one_rotation_then_revokes_family() -> None:
    database_url = os.environ["AUTH_TEST_DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    ordered_tables = [
        Tenant.__table__,
        AuthUser.__table__,
        AuthSession.__table__,
        AuthRefreshTokenHistory.__table__,
    ]

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

    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    refresh_token = "R1-concurrent-refresh-token"

    seed_service = AuthService(_auth_config())
    seed_service._initialized = True

    async with session_factory() as db_session:
        async with db_session.begin():
            db_session.add(
                AuthUser(
                    user_id=user_id,
                    email="concurrency@example.test",
                    username="concurrency",
                    full_name="Concurrency Test",
                    password_hash=seed_service._hash_password("Original1!"),
                    roles=["user"],
                    preferences={},
                    is_verified=True,
                    is_active=True,
                )
            )
            db_session.add(
                AuthSession(
                    session_token=session_id,
                    user_id=user_id,
                    access_token="initial-access-token",
                    refresh_token=refresh_token,
                    expires_in=3600,
                    is_active=True,
                )
            )

    async def rotate_once() -> tuple[str | None, str | None, str | None]:
        service = AuthService(_auth_config())
        service._initialized = True
        async with session_factory() as db_session:
            async with db_session.begin():
                service.set_db_session(db_session)
                return await service.refresh_access_token(refresh_token)

    first, second = await asyncio.gather(rotate_once(), rotate_once())
    results = [first, second]

    successes = [result for result in results if result[2] is None]
    replays = [result for result in results if result[2] == "Refresh token replay detected"]

    assert len(successes) == 1
    assert len(replays) == 1
    assert successes[0][0]
    assert successes[0][1]
    assert successes[0][1] != refresh_token

    async with session_factory() as db_session:
        session_result = await db_session.execute(
            select(AuthSession).where(AuthSession.session_token == session_id)
        )
        durable_session = session_result.scalar_one()

        history_result = await db_session.execute(
            select(AuthRefreshTokenHistory).where(
                AuthRefreshTokenHistory.session_id == session_id
            )
        )
        history = history_result.scalars().all()

        assert durable_session.is_active is False
        assert durable_session.invalidation_reason == "refresh_token_replay"
        assert len(history) == 1
        assert history[0].token_hash == hashlib.sha256(refresh_token.encode()).hexdigest()
        assert history[0].replayed_at is not None

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.drop_all(
                sync_connection,
                tables=list(reversed(ordered_tables)),
                checkfirst=True,
            )
        )
    await engine.dispose()
