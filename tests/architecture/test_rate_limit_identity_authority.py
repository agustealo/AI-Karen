"""Security proofs for canonical rate-limit identity and route ownership."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import Request

from ai_karen_engine.middleware.rate_limit import (
    _extract_client_info,
    _rate_limit_endpoint,
)
from ai_karen_engine.server.rate_limiter import create_rate_limiter


ROOT = Path(__file__).resolve().parents[2]
RATE_LIMIT_MIDDLEWARE = ROOT / "src/ai_karen_engine/middleware/rate_limit.py"
AUTH_ROUTES = ROOT / "src/ai_karen_engine/api_routes/auth/auth.py"
ROUTERS = ROOT / "src/ai_karen_engine/server/routers.py"
BASE_COMPOSE = ROOT / "docker-compose.yml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _request(*, state: dict | None = None) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/auth/login",
        "raw_path": b"/api/auth/login",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"x-forwarded-for", b"203.0.113.99"),
            (b"x-real-ip", b"203.0.113.98"),
            (b"x-user-id", b"spoofed-user"),
            (b"x-user-type", b"admin"),
        ],
        "client": ("198.51.100.7", 41000),
        "server": ("testserver", 80),
        "state": dict(state or {}),
    }
    return Request(scope)


def test_client_supplied_identity_headers_cannot_select_rate_limit_buckets() -> None:
    ip_address, user_id, user_type = _extract_client_info(_request())

    assert ip_address == "198.51.100.7"
    assert user_id is None
    assert user_type is None

    source = _read(RATE_LIMIT_MIDDLEWARE).lower()
    for untrusted_header in (
        "x-forwarded-for",
        "x-real-ip",
        "x-user-id",
        "x-user-type",
    ):
        assert untrusted_header not in source


def test_authenticated_principal_is_the_only_user_bucket_identity() -> None:
    request = _request(
        state={
            "user": {
                "user_id": "canonical-user-1",
                "tenant_id": "canonical-tenant-1",
                "user_type": "member",
            }
        }
    )

    ip_address, user_id, user_type = _extract_client_info(request)

    assert ip_address == "198.51.100.7"
    assert user_id == "canonical-user-1"
    assert user_type == "member"


def test_anonymous_principal_does_not_create_a_user_bucket() -> None:
    request = _request(
        state={
            "user": {
                "user_id": "anonymous",
                "user_type": "anonymous",
                "authenticated": False,
            }
        }
    )

    _, user_id, user_type = _extract_client_info(request)
    assert user_id is None
    assert user_type is None


def test_mounted_api_path_is_normalized_to_rate_limit_rule_contract() -> None:
    assert _rate_limit_endpoint("/api/auth/login") == "/auth/login"
    assert _rate_limit_endpoint("/api/chat") == "/chat"
    assert _rate_limit_endpoint("/health") == "/health"

    auth_routes = _read(AUTH_ROUTES)
    routers = _read(ROUTERS)
    assert 'router = APIRouter(prefix="/auth"' in auth_routes
    assert 'RouterSpec(auth_router, "/api"' in routers


def test_canonical_login_hits_the_strict_ip_rule() -> None:
    limiter = create_rate_limiter(storage_type="memory")
    result = asyncio.run(
        limiter.check_rate_limit(
            ip_address="198.51.100.7",
            endpoint=_rate_limit_endpoint("/api/auth/login"),
            user_id=None,
            user_type=None,
        )
    )

    assert result.rule_name == "auth_strict"
    assert result.limit == 10
    assert result.window_seconds == 60


def test_production_stack_keeps_global_rate_limiting_enabled() -> None:
    compose = _read(BASE_COMPOSE)
    assert 'ENABLE_RATE_LIMITING: "true"' in compose
    assert 'AUTH_ENABLE_RATE_LIMITING: "true"' in compose
