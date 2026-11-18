"""High-risk plugin management must use a current canonical bearer session.

A user profile, signed request header, synthetic development identity, cookie,
or unverified token claims are not a lifecycle authorization credential.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request

from ai_karen_engine.auth import auth_middleware, rbac_middleware, session


def _request(*, bearer: str | None = "verified-token", cookie: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if bearer is not None:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))
    if cookie is not None:
        headers.append((b"cookie", f"kari_session={cookie}".encode()))
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/plugins/timezone-clock/lifecycle/enable/approval",
        "root_path": "",
        "scheme": "https",
        "headers": headers,
        "query_string": b"",
        "server": ("localhost", 443),
    })


def _identity() -> dict[str, object]:
    return {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "roles": ["admin"],
        "permissions": [],
        "token_id": "server-signed-active-session-1",
    }


def _install_authenticated_backend(
    monkeypatch: pytest.MonkeyPatch,
    *,
    payload: dict[str, object] | None = None,
    token_status: auth_middleware.TokenStatus = auth_middleware.TokenStatus.VALID,
    status_code: int = 401,
    manage_allowed: bool = True,
):
    verified = dict(payload) if payload is not None else _identity()
    validator = SimpleNamespace(
        validate_token=AsyncMock(return_value={
            "status": token_status,
            "http_status": status_code,
            "payload": verified,
        }),
        _get_user_from_payload=lambda item: {
            "user_id": item.get("sub"),
            "tenant_id": item.get("tenant_id"),
            "roles": item.get("roles", []),
            "permissions": item.get("permissions", []),
        },
    )
    audits: list[dict[str, object]] = []

    class RBAC:
        def has_permission(self, principal, permission):
            return manage_allowed and "admin" in principal.roles

        def audit_access_attempt(self, principal, permission, **kwargs):
            audits.append({
                "actor": principal.user_id,
                "permission": permission,
                "granted": kwargs["granted"],
            })

    monkeypatch.setattr(session.auth_config, "should_bypass_auth", lambda: False)
    monkeypatch.setattr(session, "_get_auth_middleware", lambda: validator)
    monkeypatch.setattr(rbac_middleware, "get_rbac_manager", lambda: RBAC())
    return validator, verified, audits


@pytest.mark.asyncio
async def test_current_bearer_session_is_only_lifecycle_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator, claims, audits = _install_authenticated_backend(monkeypatch)
    request = _request()
    request.state.request_id = "trusted-request-1"
    request.state.correlation_id = "trusted-correlation-1"
    context = await session.get_plugin_lifecycle_context(request)

    assert context.user_id == claims["sub"]
    assert context.tenant_id == claims["tenant_id"]
    assert context.session_id == claims["token_id"]
    assert context.conversation_id == str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"ai-karen:conversation:{claims['tenant_id']}:{claims['token_id']}",
        )
    )
    assert context.request_id == "trusted-request-1"
    assert context.correlation_id == "trusted-correlation-1"
    assert context.require_authenticated_user().user_id == claims["sub"]
    assert context.permissions == []
    assert audits[0]["granted"] is True
    validator.validate_token.assert_awaited_once_with("verified-token")


@pytest.mark.asyncio
async def test_changed_active_token_is_different_immutable_approval_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator, claims, _ = _install_authenticated_backend(monkeypatch)
    before = await session.get_plugin_lifecycle_context(_request())
    replacement = {**claims, "token_id": "new-verified-active-session"}
    validator.validate_token.return_value = {
        "status": auth_middleware.TokenStatus.VALID,
        "payload": replacement,
    }
    after = await session.get_plugin_lifecycle_context(_request())
    assert before.user_id == after.user_id
    assert before.session_id != after.session_id
    assert before.conversation_id != after.conversation_id


@pytest.mark.asyncio
@pytest.mark.parametrize("bearer,cookie", [
    (None, None),
    (None, "cookie-only-login"),
    ("", None),
    ("bad token with spaces", None),
])
async def test_browser_cookie_or_untrusted_bearer_never_authorizes_mutation(
    monkeypatch: pytest.MonkeyPatch,
    bearer: str | None,
    cookie: str | None,
) -> None:
    validator, _, _ = _install_authenticated_backend(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await session.get_plugin_lifecycle_context(
            _request(bearer=bearer, cookie=cookie)
        )
    assert exc.value.status_code == 401
    validator.validate_token.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("token_status,http_status,expected", [
    (auth_middleware.TokenStatus.INVALID, 401, 401),
    (auth_middleware.TokenStatus.REVOKED, 401, 401),
    (auth_middleware.TokenStatus.EXPIRED, 401, 401),
    (auth_middleware.TokenStatus.INVALID, 503, 503),
])
async def test_denied_or_unavailable_active_session_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    token_status: auth_middleware.TokenStatus,
    http_status: int,
    expected: int,
) -> None:
    _install_authenticated_backend(
        monkeypatch, token_status=token_status, status_code=http_status,
    )
    with pytest.raises(HTTPException) as exc:
        await session.get_plugin_lifecycle_context(_request())
    assert exc.value.status_code == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("modified", [
    {"token_id": None},
    {"token_id": "invalid session with spaces"},
    {"type": "refresh"},
    {"tenant_id": "default"},
    {"tenant_id": "not-a-uuid"},
    {"sub": "forged-user"},
    {"roles": ["user"]},
])
async def test_invalid_claims_cannot_mint_lifecycle_actor_and_session(
    monkeypatch: pytest.MonkeyPatch,
    modified: dict[str, object],
) -> None:
    claims = {**_identity(), **modified}
    _install_authenticated_backend(monkeypatch, payload=claims)
    with pytest.raises(HTTPException) as exc:
        await session.get_plugin_lifecycle_context(_request())
    assert exc.value.status_code in {401, 403}


@pytest.mark.asyncio
async def test_dev_auth_bypass_never_grants_lifecycle_management(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator, _, _ = _install_authenticated_backend(monkeypatch)
    monkeypatch.setattr(session.auth_config, "should_bypass_auth", lambda: True)
    with pytest.raises(HTTPException) as exc:
        await session.get_plugin_lifecycle_context(_request())
    assert exc.value.status_code == 403
    validator.validate_token.assert_not_awaited()
