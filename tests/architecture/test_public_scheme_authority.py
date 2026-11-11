"""Security proofs for canonical public-scheme and session-cookie authority."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
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


@pytest.mark.parametrize("scheme", [None, "", "ftp", "https,http", "https://", "http://", "h2"])
def test_web_ingress_rejects_missing_or_invalid_scheme_before_next_import(scheme) -> None:
    """A bad scheme must terminate immediately even without installed Next.js."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable; production Docker first-boot gate remains required")
    env = os.environ.copy()
    if scheme is None:
        env.pop("WEB_PUBLIC_SCHEME", None)
    else:
        env["WEB_PUBLIC_SCHEME"] = scheme
    result = subprocess.run(
        [node, str(WEB_INGRESS)],
        cwd=WEB_INGRESS.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )
    assert result.returncode != 0
    assert 'WEB_PUBLIC_SCHEME must be explicitly configured as "http" or "https"' in result.stderr


def test_web_ingress_validates_scheme_before_initializing_nextjs() -> None:
    source = _read(WEB_INGRESS)
    validation = source.index("publicScheme !== 'http' && publicScheme !== 'https'")
    framework_import = source.index("await import('next')")
    listener = source.index("server.listen(")
    assert validation < framework_import < listener
    assert "import next from 'next'" not in source


def test_production_image_scheme_smoke_rejects_malformed_values_not_just_missing() -> None:
    """Built image proof must fail closed for every invalid ingress configuration."""
    workflow = _read(FIRST_BOOT_WORKFLOW)
    title = "      - name: Prove web ingress rejects missing or malformed public scheme"
    assert workflow.count(title) == 1
    step = workflow.split(title, 1)[1].split(
        "\n      - name: Execute real production first boot", 1
    )[0]

    assert 'for case_name in missing empty unsupported comma_list url_form; do' in step
    assert 'missing) ;;' in step
    assert 'empty) scheme_env=(-e WEB_PUBLIC_SCHEME=) ;;' in step
    assert 'unsupported) scheme_env=(-e WEB_PUBLIC_SCHEME=ftp) ;;' in step
    assert 'comma_list) scheme_env=(-e WEB_PUBLIC_SCHEME=https,http) ;;' in step
    assert 'url_form) scheme_env=(-e WEB_PUBLIC_SCHEME=https://) ;;' in step
    assert 'timeout 15s docker run --rm "${scheme_env[@]}" ai-karen-web:beta' in step
    assert 'if [ "$status" -eq 0 ] || [ "$status" -eq 124 ]; then' in step
    assert 'grep -Fq \'WEB_PUBLIC_SCHEME must be explicitly configured as "http" or "https"\'' in step
    assert 'trap \'rm -rf "$log_dir"\' EXIT' in step
    assert "-e WEB_PUBLIC_SCHEME=http" in workflow
    # Do not replace the production-image check with an untrusted source-only
    # mock or an HTTP liveness check that passes after misconfigured startup.
    assert "docker run --rm" in step
    assert "node --eval" not in step
