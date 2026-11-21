"""KUI-002D3C: signed-session enforcement through the actual pin HTTP ingress.

No dependency override supplies a principal. Canonical JWT verification,
active-session authorization, tenant identity comparison and FastAPI dependency
resolution all execute. Only durable session outcomes and the terminal pin
mutation are controlled test fixtures. This is not a live hosted auth test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ai_karen_engine.api_routes.chat import runtime as ingress
from ai_karen_engine.auth import auth_middleware
from ai_karen_engine.auth import auth_service as auth_facade
from ai_karen_engine.core.runtime.presentation_pin_mutation import PresentationPinMutation
from ai_karen_engine.core.security.auth_config import auth_config

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_TENANT = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER = "11111111-1111-1111-1111-111111111111"
PIN = "88888888-8888-4888-8888-888888888888"
KEY = "55555555-5555-4555-8555-555555555555"
RECEIPT = "99999999-9999-4999-8999-999999999999"
JWT_SECRET = "kui-002d3c-isolated-session-proof-secret"


def signed_token(*, tenant: str = TENANT, user: str = USER) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": user,
            "tenant_id": tenant,
            "token_id": "kui-002d3c-test-token",
            "roles": ["admin"],
            "permissions": ["forged:grant"],
            "email": "stale@example.org",
            "iss": "ai-karen",
            "aud": "ai-karen-users",
            "iat": now,
            "exp": now + timedelta(minutes=10),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def active_account(*, tenant: str = TENANT, user: str = USER):
    return SimpleNamespace(
        id=user,
        tenant_id=tenant,
        roles=["user"],
        email="current@example.org",
    )


def prepared_app(monkeypatch, *, validated_account=None, validation_error=None):
    """Keep real auth dependency and token/session validators in the route."""
    monkeypatch.setattr(auth_config, "should_bypass_auth", lambda: False)
    monkeypatch.setattr(
        ingress,
        "get_runtime_settings",
        lambda: SimpleNamespace(features=SimpleNamespace(
            enable_ag_ui_bridge=True,
            enable_ag_ui_durable_runs=True,
            enable_presentation_pin_mutations=True,
        )),
    )

    middleware = object.__new__(auth_middleware.SecureAuthMiddleware)
    middleware.jwt_secret = JWT_SECRET
    middleware.jwt_algorithm = "HS256"
    middleware.redis_client = None
    monkeypatch.setattr(auth_middleware, "get_auth_middleware", lambda: middleware)

    session_validation = AsyncMock(
        side_effect=validation_error
        if validation_error is not None else None,
        return_value=validated_account,
    )
    service = SimpleNamespace(validate_session=session_validation)
    monkeypatch.setattr(auth_facade, "get_auth_service", AsyncMock(return_value=service))

    committed = SimpleNamespace(
        receipt_id=RECEIPT,
        idempotency_key=KEY,
        request_id="server-request",
        correlation_id="server-correlation",
        operation="unpin",
        outcome="unpinned",
        pin_id=PIN,
        expected_revision=None,
        committed_revision=1,
    )
    mutate = AsyncMock(return_value=committed)
    monkeypatch.setattr(PresentationPinMutation, "execute", mutate)

    app = FastAPI()
    app.include_router(ingress.router)
    assert not app.dependency_overrides
    return app, session_validation, mutate


async def post_mutation(app, *, token: str, body=None):
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as http:
        return await http.post(
            "/chat/ag-ui/pins/mutations",
            headers={"Authorization": f"Bearer {token}"},
            json=body or {
                "operation": "unpin",
                "idempotency_key": KEY,
                "pin_id": PIN,
            },
        )


@pytest.mark.asyncio
async def test_valid_signed_durable_session_reaches_runtime_with_canonical_identity(monkeypatch):
    app, session_validation, mutate = prepared_app(
        monkeypatch, validated_account=active_account()
    )
    token = signed_token()
    response = await post_mutation(app, token=token)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["receipt"]["receipt_id"] == RECEIPT

    session_validation.assert_awaited_once_with(token, strict_errors=True)
    mutate.assert_awaited_once()
    context = mutate.await_args.kwargs["context"]
    assert context.user_id == USER
    assert context.tenant_id == TENANT
    assert context.require_authenticated_user().user_id == USER
    assert context.roles == ["user"]
    assert context.permissions == []
    assert context.request_id and context.correlation_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "durable_account,failure",
    [
        (None, None),  # Revoked/expired in canonical durable session.
        (active_account(tenant=OTHER_TENANT), None),  # Signed stale tenant claim.
        (active_account(user="22222222-2222-4222-8222-222222222222"), None),
        (None, RuntimeError("durable PostgreSQL session store unavailable")),
    ],
)
async def test_rejected_or_unavailable_session_never_executes_mutation(
    monkeypatch, durable_account, failure
):
    app, validation, mutate = prepared_app(
        monkeypatch,
        validated_account=durable_account,
        validation_error=failure,
    )
    token = signed_token()
    response = await post_mutation(app, token=token)
    assert response.status_code == 401
    assert "committed" not in response.text
    validation.assert_awaited_once_with(token, strict_errors=True)
    mutate.assert_not_awaited()


@pytest.mark.asyncio
async def test_client_cannot_override_authenticated_scope_in_mutation_body(monkeypatch):
    app, _, mutate = prepared_app(monkeypatch, validated_account=active_account())
    response = await post_mutation(
        app,
        token=signed_token(),
        body={
            "operation": "unpin",
            "idempotency_key": KEY,
            "pin_id": PIN,
            "tenant_id": OTHER_TENANT,
            "user_id": "22222222-2222-4222-8222-222222222222",
            "roles": ["admin"],
        },
    )
    assert response.status_code == 200, response.text
    context = mutate.await_args.kwargs["context"]
    assert context.tenant_id == TENANT
    assert context.user_id == USER
    assert context.roles == ["user"]
    assert context.permissions == []
