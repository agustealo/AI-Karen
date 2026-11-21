"""KUI-002D3D: live PostgreSQL active sessions through canonical pin HTTP ingress.

Uses only the explicit disposable karen_presentation_pin_test database.
The canonical AuthService executes SQLAlchemy AuthSession/AuthUser queries
against PostgreSQL. Only the mutation executor is stubbed, preventing this
auth-focused contract from making unrelated pin ledger writes.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlparse

import asyncpg
import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.api_routes.chat import runtime as ingress
from ai_karen_engine.auth import auth_middleware, auth_service as auth_facade
from ai_karen_engine.core.runtime.presentation_pin_mutation import PresentationPinMutation
from ai_karen_engine.core.security.auth_config import auth_config
from ai_karen_engine.database.models import AuthSession, AuthUser, Tenant
from ai_karen_engine.services.auth.auth_service import AuthService

pytestmark = pytest.mark.asyncio

PIN = "88888888-8888-4888-8888-888888888888"
KEY = "55555555-5555-4555-8555-555555555555"
JWT_SECRET = "kui-002d3d-disposable-postgres-secret"


async def test_real_postgres_session_authority_blocks_revoked_and_drifted_http_mutations(
    monkeypatch,
) -> None:
    if (
        os.environ.get("KAREN_TEST_PIN_POSTGRES") != "1"
        or os.environ.get("KAREN_TEST_DISPOSABLE_DATABASE") != "1"
    ):
        pytest.skip("Requires explicit disposable PostgreSQL acceptance opt-in")
    dsn = os.environ.get("KAREN_TEST_PIN_DATABASE_URL", "")
    if urlparse(dsn).path != "/karen_presentation_pin_test":
        pytest.fail("Refusing to run auth proof outside disposable pin database")

    raw = await asyncpg.connect(
        dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    )
    tables = (Tenant.__table__, AuthUser.__table__, AuthSession.__table__)
    suffix = uuid.uuid4().hex[:12]
    tenant_id, other_tenant_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": str(user_id),
            "tenant_id": str(tenant_id),
            "roles": ["admin"],
            "permissions": ["forged:admin"],
            "email": "stale@example.org",
            "iss": "ai-karen",
            "aud": "ai-karen-users",
            "iat": now,
            "exp": now + timedelta(minutes=10),
        },
        JWT_SECRET,
        algorithm="HS256",
    )

    created_by_test = False
    try:
        existing = await raw.fetchval("""
            SELECT count(*) FROM information_schema.tables
            WHERE table_schema='public'
              AND table_name IN ('tenants','auth_users','auth_sessions')
        """)
        if existing:
            pytest.fail("Database must be empty; refusing to modify existing auth schema")
        async with engine.begin() as conn:
            for table in tables:
                await conn.run_sync(table.create, checkfirst=False)

        created_by_test = True
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker.begin() as session:
            session.add_all([
                Tenant(id=tenant_id, name="KUI proof " + suffix, slug="kui-" + suffix),
                Tenant(id=other_tenant_id, name="Other proof " + suffix, slug="other-" + suffix),
            ])
        async with maker.begin() as session:
            session.add(AuthUser(
                user_id=user_id,
                tenant_id=tenant_id,
                email="kui-" + suffix + "@example.invalid",
                username="kui-" + suffix,
                roles=["user"],
                is_verified=True,
                is_active=True,
                password_hash="no-login-in-this-test",
            ))
        async with maker.begin() as session:
            session.add(AuthSession(
                session_token=uuid.uuid4(),
                user_id=user_id,
                access_token=token,
                refresh_token="disposable-refresh",
                expires_in=3600,
                created_at=datetime.utcnow(),
                last_accessed=datetime.utcnow(),
                is_active=True,
            ))

        service = object.__new__(AuthService)
        service._initialized = True
        service._config = SimpleNamespace(
            jwt_secret_key=JWT_SECRET,
            jwt_algorithm="HS256",
        )
        service._user_cache = {}

        @asynccontextmanager
        async def real_db_scope():
            async with maker() as session:
                async with session.begin():
                    yield session

        service._session_scope = real_db_scope
        monkeypatch.setattr(
            auth_facade,
            "get_auth_service",
            AsyncMock(return_value=service),
        )
        monkeypatch.setattr(auth_config, "should_bypass_auth", lambda: False)
        middleware = object.__new__(auth_middleware.SecureAuthMiddleware)
        middleware.jwt_secret = JWT_SECRET
        middleware.jwt_algorithm = "HS256"
        middleware.redis_client = None
        monkeypatch.setattr(auth_middleware, "get_auth_middleware", lambda: middleware)
        monkeypatch.setattr(
            ingress,
            "get_runtime_settings",
            lambda: SimpleNamespace(features=SimpleNamespace(
                enable_ag_ui_bridge=True,
                enable_ag_ui_durable_runs=True,
                enable_presentation_pin_mutations=True,
            )),
        )
        receipt = SimpleNamespace(
            receipt_id=str(uuid.uuid4()),
            idempotency_key=KEY,
            request_id="committed-request",
            correlation_id="committed-correlation",
            operation="unpin",
            outcome="unpinned",
            pin_id=PIN,
            expected_revision=None,
            committed_revision=None,
        )
        execute = AsyncMock(return_value=receipt)
        monkeypatch.setattr(PresentationPinMutation, "execute", execute)
        app = FastAPI()
        app.include_router(ingress.router)
        assert not app.dependency_overrides

        async def make_request():
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as client:
                return await client.post(
                    "/chat/ag-ui/pins/mutations",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"operation": "unpin", "idempotency_key": KEY, "pin_id": PIN},
                )

        accepted = await make_request()
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["committed"] is True
        execute.assert_awaited_once()
        context = execute.await_args.kwargs["context"]
        assert context.user_id == str(user_id)
        assert context.tenant_id == str(tenant_id)
        assert context.roles == ["user"]
        assert context.permissions == []
        execute.reset_mock()

        async with maker.begin() as session:
            row = (await session.execute(
                select(AuthSession).where(AuthSession.user_id == user_id)
            )).scalar_one()
            row.is_active = False
        revoked = await make_request()
        assert revoked.status_code == 401
        assert "committed" not in revoked.text
        execute.assert_not_awaited()

        async with maker.begin() as session:
            row = (await session.execute(
                select(AuthSession).where(AuthSession.user_id == user_id)
            )).scalar_one()
            row.is_active = True
            account = (await session.execute(
                select(AuthUser).where(AuthUser.user_id == user_id)
            )).scalar_one()
            account.tenant_id = other_tenant_id
        drifted = await make_request()
        assert drifted.status_code == 401
        assert "committed" not in drifted.text
        execute.assert_not_awaited()

        # A session query outage must reject the signed token instead of
        # granting JWT-only access or emitting a receipt.
        async def failed_db_scope():
            raise OSError("private session database detail")
            yield  # pragma: no cover

        service._session_scope = asynccontextmanager(failed_db_scope)
        outage = await make_request()
        assert outage.status_code == 401
        assert "committed" not in outage.text
        execute.assert_not_awaited()
    finally:
        try:
            await engine.dispose()
            if created_by_test:
                # Only the isolated disposable DB can be modified. The
                # schema created above was checked absent before startup.
                await raw.execute("DROP TABLE IF EXISTS public.auth_sessions CASCADE")
                await raw.execute("DROP TABLE IF EXISTS public.auth_users CASCADE")
                await raw.execute("DROP TABLE IF EXISTS public.tenants CASCADE")
        finally:
            await raw.close()
