"""Security proofs for canonical public-scheme and session-cookie authority."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ai_karen_engine.server.client_identity import configure_client_identity
from ai_karen_engine.server.public_origin import (
    resolve_public_scheme,
    should_use_secure_cookie,
)


ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = ROOT / "src/ai_karen_engine/server"
ENGINE_ROOT = ROOT / "src/ai_karen_engine"
PUBLIC_ORIGIN = SERVER_ROOT / "public_origin.py"
AUTH_ROUTES = ROOT / "src/ai_karen_engine/api_routes/auth/auth.py"
WEB_INGRESS = ROOT / "src/ui_launchers/Karen-AI-Theme/server.mjs"
BACKEND_PROXY = (
    ROOT
    / "src/ui_launchers/Karen-AI-Theme/src/app/api/_lib/backend-proxy.ts"
)
PROD_COMPOSE = ROOT / "deploy/compose/docker-compose.prod.yml"
PROD_ENV_EXAMPLE = ROOT / ".env.production.example"
FIRST_BOOT_WORKFLOW = ROOT / ".github/workflows/production-first-boot-smoke.yml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _request(
    *,
    peer: str = "198.51.100.7",
    scheme: str = "http",
    forwarded_proto: str | None = "https",
) -> Any:
    headers: dict[str, str] = {}
    if forwarded_proto is not None:
        headers["x-forwarded-proto"] = forwarded_proto
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        url=SimpleNamespace(scheme=scheme),
        headers=headers,
    )


def test_direct_http_request_cannot_spoof_https_scheme() -> None:
    configure_client_identity([])
    request = _request(scheme="http", forwarded_proto="https")

    assert resolve_public_scheme(request) == "http"
    assert should_use_secure_cookie(request) is False


def test_direct_https_request_cannot_be_downgraded_by_header() -> None:
    configure_client_identity([])
    request = _request(scheme="https", forwarded_proto="http")

    assert resolve_public_scheme(request) == "https"
    assert should_use_secure_cookie(request) is True


def test_trusted_proxy_may_supply_https_public_scheme() -> None:
    configure_client_identity(["198.51.100.7"])
    request = _request(peer="198.51.100.7", scheme="http", forwarded_proto="https")

    assert resolve_public_scheme(request) == "https"
    assert should_use_secure_cookie(request) is True


def test_trusted_proxy_may_explicitly_supply_http_for_plaintext_trial() -> None:
    configure_client_identity(["198.51.100.7"])
    request = _request(peer="198.51.100.7", scheme="http", forwarded_proto="http")

    assert resolve_public_scheme(request) == "http"
    assert should_use_secure_cookie(request) is False


def test_trusted_proxy_missing_or_malformed_scheme_fails_to_secure_cookie() -> None:
    configure_client_identity(["198.51.100.7"])

    missing = _request(peer="198.51.100.7", scheme="http", forwarded_proto=None)
    malformed = _request(
        peer="198.51.100.7",
        scheme="http",
        forwarded_proto="https,http",
    )

    assert resolve_public_scheme(missing) == ""
    assert resolve_public_scheme(malformed) == ""
    assert should_use_secure_cookie(missing) is True
    assert should_use_secure_cookie(malformed) is True


def test_public_origin_is_the_only_backend_forwarded_scheme_parser() -> None:
    readers: list[Path] = []
    for path in ENGINE_ROOT.rglob("*.py"):
        if "x-forwarded-proto" in _read(path).lower():
            readers.append(path.relative_to(ROOT))

    assert readers == [Path("src/ai_karen_engine/server/public_origin.py")]


def test_auth_session_cookies_use_canonical_public_scheme_authority() -> None:
    source = _read(AUTH_ROUTES)

    assert (
        "from ai_karen_engine.server.public_origin import should_use_secure_cookie"
        in source
    )
    assert source.count("secure=should_use_secure_cookie(http_request)") == 3
    assert 'secure=http_request.url.scheme == "https"' not in source
    assert "x-forwarded-proto" not in source.lower()


def test_web_ingress_overwrites_public_scheme_from_validated_config() -> None:
    source = _read(WEB_INGRESS)

    assert "process.env.WEB_PUBLIC_SCHEME" in source
    assert "publicScheme !== 'http' && publicScheme !== 'https'" in source
    assert "req.headers['x-forwarded-proto'] = publicScheme" in source


def test_backend_proxy_preserves_normalized_ingress_scheme_without_forcing_http() -> None:
    source = _read(BACKEND_PROXY)

    assert "function normalizeForwardedProto" in source
    assert "headers.get('x-forwarded-proto')" in source
    assert "nextHeaders.set('x-forwarded-proto', forwardedProto)" in source
    assert "nextHeaders.set('x-forwarded-proto', 'http')" not in source


def test_production_and_smoke_contracts_require_explicit_public_scheme() -> None:
    compose = _read(PROD_COMPOSE)
    env_example = _read(PROD_ENV_EXAMPLE)
    first_boot = _read(FIRST_BOOT_WORKFLOW)

    assert (
        "WEB_PUBLIC_SCHEME: ${WEB_PUBLIC_SCHEME:?WEB_PUBLIC_SCHEME must be http or https in production}"
        in compose
    )
    assert "WEB_PUBLIC_SCHEME=CHANGE_ME_HTTP_OR_HTTPS" in env_example
    assert "-e WEB_PUBLIC_SCHEME=http" in first_boot
