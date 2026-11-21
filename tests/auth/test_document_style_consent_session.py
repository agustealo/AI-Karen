"""WS-04A9H: document consent needs fresh bearer, not cookie or plugin-admin."""
from __future__ import annotations

import hashlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request

from ai_karen_engine.auth import auth_middleware, session


def request(bearer: str | None = "current-author-token") -> Request:
    headers = (
        [(b"authorization", ("Bearer " + bearer).encode())]
        if bearer is not None else []
    )
    return Request({
        "type": "http", "method": "POST", "path": "/internal/author-consent",
        "scheme": "https", "root_path": "", "headers": headers,
        "query_string": b"", "server": ("localhost", 443),
    })


def backend(monkeypatch, *, state=auth_middleware.TokenStatus.VALID,
            http_status=401, claims=None):
    payload = claims or {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "roles": ["user"],
        "permissions": [],
        "token_id": "active-author-session-1",
    }
    validator = SimpleNamespace(
        validate_token=AsyncMock(return_value={
            "status": state, "http_status": http_status, "payload": payload,
        }),
        _get_user_from_payload=lambda item: {
            "user_id": item.get("sub"),
            "tenant_id": item.get("tenant_id"),
            "roles": item.get("roles", []),
            "permissions": item.get("permissions", []),
        },
    )
    monkeypatch.setattr(session.auth_config, "should_bypass_auth", lambda: False)
    monkeypatch.setattr(session, "_get_auth_middleware", lambda: validator)
    return validator, payload


@pytest.mark.asyncio
async def test_non_admin_author_gets_fresh_domain_separated_session(monkeypatch):
    validator, claims = backend(monkeypatch)
    context = await session.get_document_style_consent_context(request())
    assert context.user_id == claims["sub"]
    assert context.tenant_id == claims["tenant_id"]
    assert context.require_authenticated_user().user_id == claims["sub"]
    expected = hashlib.sha256(
        f"ai-karen:writing-style-document-consent:{claims['tenant_id']}:"
        f"{claims['sub']}:{claims['token_id']}".encode()
    ).hexdigest()
    assert context.session_id == expected
    assert claims["token_id"] not in context.session_id
    validator.validate_token.assert_awaited_once_with("current-author-token")


@pytest.mark.asyncio
async def test_replaced_access_session_cannot_reuse_author_approval_scope(monkeypatch):
    validator, claims = backend(monkeypatch)
    before = await session.get_document_style_consent_context(request())
    validator.validate_token.return_value = {
        "status": auth_middleware.TokenStatus.VALID,
        "payload": {**claims, "token_id": "replacement-active-session"},
    }
    after = await session.get_document_style_consent_context(request())
    assert before.user_id == after.user_id
    assert before.session_id != after.session_id


@pytest.mark.asyncio
@pytest.mark.parametrize("bearer", [None, "", "not a bearer token"])
async def test_no_verified_bearer_cannot_enter_author_consent(monkeypatch, bearer):
    validator, _ = backend(monkeypatch)
    with pytest.raises(HTTPException) as error:
        await session.get_document_style_consent_context(request(bearer))
    assert error.value.status_code == 401
    validator.validate_token.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("state,http,code", [
    (auth_middleware.TokenStatus.INVALID, 401, 401),
    (auth_middleware.TokenStatus.REVOKED, 401, 401),
    (auth_middleware.TokenStatus.EXPIRED, 401, 401),
    (auth_middleware.TokenStatus.INVALID, 503, 503),
])
async def test_current_token_revocation_and_backend_outage_fail_closed(
    monkeypatch, state, http, code,
):
    backend(monkeypatch, state=state, http_status=http)
    with pytest.raises(HTTPException) as error:
        await session.get_document_style_consent_context(request())
    assert error.value.status_code == code


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    {"token_id": None},
    {"token_id": "untrusted token id"},
    {"type": "refresh"},
    {"tenant_id": "default"},
    {"sub": "malformed-user"},
])
async def test_untrusted_session_claims_do_not_create_author_context(monkeypatch, mutation):
    claims = {
        "sub": str(uuid.uuid4()), "tenant_id": str(uuid.uuid4()),
        "token_id": "server-session",
    }
    backend(monkeypatch, claims={**claims, **mutation})
    with pytest.raises(HTTPException) as error:
        await session.get_document_style_consent_context(request())
    assert error.value.status_code in (401, 403)


@pytest.mark.asyncio
async def test_dev_auth_bypass_never_authorizes_author_consent(monkeypatch):
    validator, _ = backend(monkeypatch)
    monkeypatch.setattr(session.auth_config, "should_bypass_auth", lambda: True)
    with pytest.raises(HTTPException) as error:
        await session.get_document_style_consent_context(request())
    assert error.value.status_code == 403
    validator.validate_token.assert_not_awaited()
