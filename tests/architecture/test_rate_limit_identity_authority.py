"""Security proofs for canonical HTTP client identity and rate-limit ownership."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ai_karen_engine.middleware.rate_limit import (
    _extract_client_info,
    _rate_limit_endpoint,
    configure_rate_limiter,
)
from ai_karen_engine.server.client_identity import (
    configure_client_identity,
    resolve_client_ip,
)
from ai_karen_engine.server.rate_limiter import (
    STRICT_AUTH_ENDPOINTS,
    create_rate_limiter,
)


ROOT = Path(__file__).resolve().parents[2]
CLIENT_IDENTITY = ROOT / "src/ai_karen_engine/server/client_identity.py"
RATE_LIMIT_MIDDLEWARE = ROOT / "src/ai_karen_engine/middleware/rate_limit.py"
SERVER_MIDDLEWARE = ROOT / "src/ai_karen_engine/server/middleware.py"
AUTH_ROUTES = ROOT / "src/ai_karen_engine/api_routes/auth/auth.py"
ROUTERS = ROOT / "src/ai_karen_engine/server/routers.py"
BASE_COMPOSE = ROOT / "docker-compose.yml"
PROD_COMPOSE = ROOT / "deploy/compose/docker-compose.prod.yml"
WEB_INGRESS = ROOT / "src/ui_launchers/Karen-AI-Theme/server.mjs"
WEB_DOCKERFILE = ROOT / "src/ui_launchers/Karen-AI-Theme/Dockerfile.production"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _request(
    *,
    peer: str = "198.51.100.7",
    forwarded_for: str = "203.0.113.99",
    state: dict[str, Any] | None = None,
) -> Any:
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        state=SimpleNamespace(**dict(state or {})),
        headers={
            "x-forwarded-for": forwarded_for,
            "x-real-ip": "203.0.113.98",
            "x-user-id": "spoofed-user",
            "x-user-type": "admin",
        },
    )


def _configure_trust(*hosts: str) -> None:
    configure_client_identity(hosts)
    configure_rate_limiter(storage_type="memory")


def test_direct_client_cannot_spoof_transport_or_rate_limit_identity() -> None:
    _configure_trust()
    request = _request()

    assert resolve_client_ip(request) == "198.51.100.7"
    ip_address, user_id, user_type = _extract_client_info(request)
    assert ip_address == "198.51.100.7"
    assert user_id is None
    assert user_type is None

    source = _read(RATE_LIMIT_MIDDLEWARE).lower()
    assert 'request.headers.get("x-user-id")' not in source
    assert 'request.headers.get("x-user-type")' not in source
    assert "x-forwarded-for" not in source
    assert "x-real-ip" not in source


def test_trusted_proxy_preserves_distinct_forwarded_client_identity() -> None:
    _configure_trust("198.51.100.7")

    first_request = _request(peer="198.51.100.7", forwarded_for="203.0.113.10")
    second_request = _request(peer="198.51.100.7", forwarded_for="203.0.113.11")

    assert resolve_client_ip(first_request) == "203.0.113.10"
    assert resolve_client_ip(second_request) == "203.0.113.11"

    first, _, _ = _extract_client_info(first_request)
    second, _, _ = _extract_client_info(second_request)
    assert first == "203.0.113.10"
    assert second == "203.0.113.11"
    assert first != second


def test_untrusted_peer_still_cannot_use_forwarded_client_identity() -> None:
    _configure_trust("192.0.2.40")
    request = _request(peer="198.51.100.7", forwarded_for="203.0.113.10")
    assert resolve_client_ip(request) == "198.51.100.7"

    ip_address, _, _ = _extract_client_info(request)
    assert ip_address == "198.51.100.7"


def test_trusted_proxy_rejects_forwarded_chains_instead_of_sharing_proxy_identity() -> None:
    _configure_trust("198.51.100.7")
    request = _request(
        peer="198.51.100.7",
        forwarded_for="192.0.2.99, 203.0.113.10",
    )
    assert resolve_client_ip(request) == ""

    ip_address, _, _ = _extract_client_info(request)
    assert ip_address == ""


def test_auth_and_rate_limit_consume_server_owned_client_identity_authority() -> None:
    auth_source = _read(AUTH_ROUTES)
    auth_source_lower = auth_source.lower()
    identity_source = _read(CLIENT_IDENTITY).lower()
    rate_limit_source = _read(RATE_LIMIT_MIDDLEWARE)
    middleware_source = _read(SERVER_MIDDLEWARE)

    canonical_resolver_import = (
        "from ai_karen_engine.server.client_identity import resolve_client_ip"
    )
    canonical_config_import = (
        "from ai_karen_engine.server.client_identity import configure_client_identity"
    )

    assert canonical_resolver_import in auth_source
    assert canonical_resolver_import in rate_limit_source
    assert canonical_config_import in middleware_source
    assert "ai_karen_engine.middleware.client_identity" not in auth_source
    assert "ai_karen_engine.middleware.client_identity" not in rate_limit_source
    assert "ai_karen_engine.middleware.client_identity" not in middleware_source

    assert "def get_client_ip(" not in auth_source
    assert "x-forwarded-for" not in auth_source_lower
    assert "x-real-ip" not in auth_source_lower
    assert "ip_address=resolve_client_ip(http_request)" in auth_source

    assert "x-forwarded-for" in identity_source
    assert "http_trusted_proxy_hosts" in identity_source
    assert "configure_client_identity()" in middleware_source


def test_authenticated_principal_is_the_only_user_bucket_identity() -> None:
    _configure_trust()
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
    _configure_trust()
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


def test_strict_auth_registry_matches_live_public_session_minting_routes() -> None:
    expected = (
        "/auth/first-run/setup",
        "/auth/login",
        "/auth/refresh",
    )
    assert STRICT_AUTH_ENDPOINTS == expected

    auth_routes = _read(AUTH_ROUTES)
    for endpoint in expected:
        route_path = endpoint.removeprefix("/auth")
        assert f'@router.post("{route_path}")' in auth_routes

    assert "/auth/register" not in STRICT_AUTH_ENDPOINTS
    assert "/auth/reset-password" not in STRICT_AUTH_ENDPOINTS


def test_all_canonical_public_auth_edges_hit_the_strict_ip_rule() -> None:
    limiter = create_rate_limiter(storage_type="memory")

    for endpoint in STRICT_AUTH_ENDPOINTS:
        result = asyncio.run(
            limiter.check_rate_limit(
                ip_address="198.51.100.7",
                endpoint=_rate_limit_endpoint(f"/api{endpoint}"),
                user_id=None,
                user_type=None,
            )
        )
        assert result.rule_name == "auth_strict"
        assert result.limit == 10
        assert result.window_seconds == 60


def test_retired_auth_paths_no_longer_select_the_strict_rule() -> None:
    limiter = create_rate_limiter(storage_type="memory")

    for endpoint in ("/auth/register", "/auth/reset-password"):
        result = asyncio.run(
            limiter.check_rate_limit(
                ip_address="198.51.100.7",
                endpoint=endpoint,
                user_id=None,
                user_type=None,
            )
        )
        assert result.rule_name == "ip_general"


def test_authenticated_auth_management_stays_on_user_policy() -> None:
    limiter = create_rate_limiter(storage_type="memory")
    result = asyncio.run(
        limiter.check_rate_limit(
            ip_address="198.51.100.7",
            endpoint="/auth/change-password",
            user_id="canonical-user-1",
            user_type="member",
        )
    )

    assert result.rule_name == "user_general"


def test_production_stack_uses_web_as_the_only_public_proxy_authority() -> None:
    base_compose = _read(BASE_COMPOSE)
    prod_compose = _read(PROD_COMPOSE)
    ingress = _read(WEB_INGRESS)
    dockerfile = _read(WEB_DOCKERFILE)

    assert 'ENABLE_RATE_LIMITING: "true"' in base_compose
    assert 'AUTH_ENABLE_RATE_LIMITING: "true"' in base_compose
    assert 'HTTP_TRUSTED_PROXY_HOSTS: "web"' in prod_compose
    assert "RATE_LIMIT_TRUSTED_PROXY_HOSTS" not in prod_compose
    assert "  api:\n    env_file: !reset []\n    ports: !reset []" in prod_compose

    assert "req.socket.remoteAddress" in ingress
    assert "req.headers['x-forwarded-for'] = clientIp" in ingress
    assert "req.headers['x-real-ip'] = clientIp" in ingress
    assert "COPY --from=builder --chown=nextjs:nodejs /app/server.mjs ./server.mjs" in dockerfile
    assert 'CMD ["node", "server.mjs"]' in dockerfile
