"""Prove Card Studio HTTP admission against real durable authenticated sessions.

Runs only on an empty, explicitly disposable PostgreSQL database. The runtime
mutation is deliberately not executed: the separate Card Studio PostgreSQL
test proves repository commits and RLS, while this test proves the canonical
auth middleware denies revoked and tenant-drifted signed sessions.
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

from ai_karen_engine.api_routes.chat import card_studio, runtime as chat_ingress
from ai_karen_engine.auth import auth_middleware, auth_service as auth_facade
from ai_karen_engine.core.runtime.card_studio_template_service import (
    CardStudioMutation,
    CardStudioTemplateService,
)
from ai_karen_engine.core.security.auth_config import auth_config
from ai_karen_engine.database.models import AuthSession, AuthUser, Tenant
from ai_karen_engine.persistence.repositories.card_studio_template_repository import (
    CardTemplateMutationReceipt,
    SavedCardTemplate,
)
from ai_karen_engine.services.auth.auth_service import AuthService

pytestmark = pytest.mark.asyncio
_DATABASE = "karen_card_studio_auth_test"
_SECRET = "disposable-card-studio-session-verification"


def _database_url():
    if (
        os.getenv("KAREN_TEST_CARD_STUDIO_POSTGRES") != "1"
        or os.getenv("KAREN_TEST_DISPOSABLE_DATABASE") != "1"
    ):
        pytest.skip("Requires approved disposable PostgreSQL")
    dsn = os.getenv("KAREN_TEST_CARD_STUDIO_AUTH_DATABASE_URL", "")
    parsed = urlparse(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    if (
        parsed.scheme != "postgresql"
        or parsed.path != f"/{_DATABASE}"
        or parsed.hostname not in ("127.0.0.1", "localhost")
        or parsed.username != "postgres"
    ):
        pytest.fail("Refusing to modify a non-disposable Card Studio auth database")
    return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


async def test_real_signed_card_studio_http_revocation_and_tenant_drift(monkeypatch):
    dsn = _database_url()
    raw = await asyncpg.connect(dsn)
    engine = create_async_engine(dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    tenant, other_tenant, owner = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": str(owner), "tenant_id": str(tenant),
            "roles": ["admin"], "permissions": ["card_studio:write"],
            "iss": "ai-karen", "aud": "ai-karen-users",
            "iat": now, "exp": now + timedelta(minutes=10),
        },
        _SECRET, algorithm="HS256",
    )
    committed = SavedCardTemplate(
        template_id=str(uuid.uuid4()), tenant_id=str(tenant), user_id=str(owner),
        template_key="verified-clock", revision=1, lifecycle="draft",
        definition={
            "schema_version": 1, "template_key": "verified-clock",
            "title": "Verified time", "layout": "stack",
            "density": "comfortable", "interaction_mode": "read_only",
            "slots": [{"slot_id": "main", "component_type": "time.observation"}],
        },
    )
    receipt = CardTemplateMutationReceipt(
        template_id=committed.template_id, revision=1, operation="create",
        idempotency_key=str(uuid.uuid4()), request_digest="a" * 64,
    )
    execute = AsyncMock(return_value=CardStudioMutation(committed, receipt))
    try:
        if await raw.fetchval("""
            SELECT count(*) FROM information_schema.tables
            WHERE table_schema='public'
              AND table_name IN ('tenants','auth_users','auth_sessions')
        """):
            pytest.fail("Refusing prepopulated auth database")

        async with engine.begin() as connection:
            for table in (Tenant.__table__, AuthUser.__table__, AuthSession.__table__):
                await connection.run_sync(table.create, checkfirst=False)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker.begin() as session:
            session.add_all([
                Tenant(id=tenant, name="Card tenant", slug="card-auth-tenant"),
                Tenant(id=other_tenant, name="Other tenant", slug="card-auth-other"),
            ])
        async with maker.begin() as session:
            session.add(AuthUser(
                user_id=owner, tenant_id=tenant,
                email="card-auth@example.invalid", username="card-auth-test",
                roles=["user"], is_verified=True, is_active=True,
                password_hash="non-login-ci-account",
            ))
        async with maker.begin() as session:
            session.add(AuthSession(
                session_token=uuid.uuid4(), user_id=owner,
                access_token=token, refresh_token="disposable-refresh",
                expires_in=3600, created_at=datetime.utcnow(),
                last_accessed=datetime.utcnow(), is_active=True,
            ))

        service = object.__new__(AuthService)
        service._initialized = True
        service._config = SimpleNamespace(
            jwt_secret_key=_SECRET, jwt_algorithm="HS256",
        )
        service._user_cache = {}

        @asynccontextmanager
        async def real_auth_scope():
            async with maker() as session:
                async with session.begin():
                    yield session

        service._session_scope = real_auth_scope
        monkeypatch.setattr(
            auth_facade, "get_auth_service",
            AsyncMock(return_value=service),
        )
        monkeypatch.setattr(auth_config, "should_bypass_auth", lambda: False)
        middleware = object.__new__(auth_middleware.SecureAuthMiddleware)
        middleware.jwt_secret = _SECRET
        middleware.jwt_algorithm = "HS256"
        middleware.redis_client = None
        monkeypatch.setattr(auth_middleware, "get_auth_middleware", lambda: middleware)
        monkeypatch.setattr(
            card_studio, "get_runtime_settings",
            lambda: SimpleNamespace(
                features=SimpleNamespace(enable_card_studio_crud=True),
            ),
        )
        monkeypatch.setattr(CardStudioTemplateService, "mutate", execute)
        app = FastAPI()
        app.include_router(chat_ingress.router)
        assert not app.dependency_overrides

        async def create():
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as client:
                return await client.post(
                    "/chat/card-studio/templates",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "idempotency_key": receipt.idempotency_key,
                        "draft": committed.definition,
                    },
                )

        allowed = await create()
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["committed"] is True
        assert execute.await_count == 1
        context = execute.await_args.kwargs["context"]
        assert context.user_id == str(owner)
        assert context.tenant_id == str(tenant)
        assert context.roles == ["user"]  # durable identity, not JWT's forged admin
        execute.reset_mock()

        async with maker.begin() as session:
            identity = (await session.execute(
                select(AuthSession).where(AuthSession.user_id == owner)
            )).scalar_one()
            identity.is_active = False
        revoked = await create()
        assert revoked.status_code == 401
        assert "committed" not in revoked.text
        execute.assert_not_awaited()

        async with maker.begin() as session:
            identity = (await session.execute(
                select(AuthSession).where(AuthSession.user_id == owner)
            )).scalar_one()
            identity.is_active = True
            principal = (await session.execute(
                select(AuthUser).where(AuthUser.user_id == owner)
            )).scalar_one()
            principal.tenant_id = other_tenant
        drifted = await create()
        assert drifted.status_code == 401
        assert "committed" not in drifted.text
        execute.assert_not_awaited()
    finally:
        await engine.dispose()
        await raw.close()
