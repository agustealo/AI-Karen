from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException, Request

from ai_karen_engine.auth import session as session_auth
from ai_karen_engine.core.security.auth_config import (
    DevelopmentIdentityConfigurationError,
    auth_config,
)


ROOT = Path(__file__).resolve().parents[2]
SERVER_ROUTERS = ROOT / "src/ai_karen_engine/server/routers.py"
SESSION_AUTH = ROOT / "src/ai_karen_engine/auth/session.py"
AUTH_CONFIG = ROOT / "src/ai_karen_engine/core/security/auth_config.py"


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/settings/behavior",
            "raw_path": b"/api/settings/behavior",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )


def test_dev_identity_uses_explicit_kari_configuration(monkeypatch) -> None:
    monkeypatch.setenv("KARI_DEV_USER_ID", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("KARI_DEV_TENANT_ID", "tenant-dev")
    monkeypatch.setenv("KARI_DEV_EMAIL", "dev@example.invalid")
    monkeypatch.setenv("KARI_DEV_ROLES", "admin,user")
    monkeypatch.setenv("KARI_DEV_PERMISSIONS", "chat:write,settings:write")

    principal = auth_config.get_dev_user_context()

    assert principal["user_id"] == "11111111-1111-1111-1111-111111111111"
    assert principal["tenant_id"] == "tenant-dev"
    assert principal["email"] == "dev@example.invalid"
    assert principal["roles"] == ["admin", "user"]
    assert principal["permissions"] == ["chat:write", "settings:write"]
    assert principal["auth_source"] == "configured_development_bypass"
    assert principal["authenticated"] is True


@pytest.mark.parametrize(
    ("user_id", "tenant_id"),
    [
        ("", "tenant-dev"),
        ("11111111-1111-1111-1111-111111111111", ""),
        ("11111111-1111-1111-1111-111111111111", "default"),
    ],
)
def test_dev_identity_fails_closed_without_authoritative_scope(
    monkeypatch,
    user_id: str,
    tenant_id: str,
) -> None:
    monkeypatch.setenv("KARI_DEV_USER_ID", user_id)
    monkeypatch.setenv("KARI_DEV_TENANT_ID", tenant_id)

    with pytest.raises(DevelopmentIdentityConfigurationError):
        auth_config.get_dev_user_context()


@pytest.mark.asyncio
async def test_session_bypass_consumes_canonical_dev_identity(monkeypatch) -> None:
    monkeypatch.setenv("KARI_DEV_USER_ID", "22222222-2222-2222-2222-222222222222")
    monkeypatch.setenv("KARI_DEV_TENANT_ID", "tenant-session")
    monkeypatch.setenv("KARI_DEV_ROLES", "user")
    monkeypatch.setattr(auth_config, "should_bypass_auth", lambda: True)

    payload = await session_auth._authenticate_request(_request())

    assert payload == auth_config.get_dev_user_context()
    assert payload["user_id"] == "22222222-2222-2222-2222-222222222222"
    assert payload["tenant_id"] == "tenant-session"


@pytest.mark.asyncio
async def test_session_bypass_translates_missing_identity_to_503(monkeypatch) -> None:
    monkeypatch.delenv("KARI_DEV_USER_ID", raising=False)
    monkeypatch.delenv("KARI_DEV_TENANT_ID", raising=False)
    monkeypatch.setattr(auth_config, "should_bypass_auth", lambda: True)

    with pytest.raises(HTTPException) as exc_info:
        await session_auth._authenticate_request(_request())

    assert exc_info.value.status_code == 503
    assert "KARI_DEV_USER_ID" in str(exc_info.value.detail)
    assert "KARI_DEV_TENANT_ID" in str(exc_info.value.detail)


def test_dev_identity_has_one_runtime_owner() -> None:
    auth_source = AUTH_CONFIG.read_text(encoding="utf-8")
    session_source = SESSION_AUTH.read_text(encoding="utf-8")
    router_source = SERVER_ROUTERS.read_text(encoding="utf-8")

    assert "get_dev_user_context" in auth_source
    assert "auth_config.get_dev_user_context()" in session_source
    assert "auth_config.get_dev_user_context()" in router_source

    assert "_configured_development_identity" not in router_source
    assert "KAREN_DEV_TENANT_ID" not in session_source
    assert '"user_id": "dev-user"' not in auth_source
    assert '"user_id": "dev-user"' not in session_source
    assert "dev-user-123" not in auth_source
