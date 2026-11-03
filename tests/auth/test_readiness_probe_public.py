"""KCHAT-P0-01: the canonical readiness probe must be reachable without auth.

The web ``/api/health`` gate proxies to backend ``/ready``. When ``/ready``
required a bearer token the consumer gate could never report
``backend_ready: true``, blocking real-browser acceptance. The exemption must
be exact so that it never exposes sibling paths by prefix.
"""

import pytest

from ai_karen_engine.auth.auth_middleware import SecureAuthMiddleware


@pytest.fixture
def middleware() -> SecureAuthMiddleware:
    return SecureAuthMiddleware.__new__(SecureAuthMiddleware)


@pytest.mark.parametrize("path", ["/ready", "/ping", "/api/ping"])
def test_operational_probes_are_public(middleware, path):
    assert middleware.is_public_endpoint(path) is True


@pytest.mark.parametrize(
    "path",
    ["/readyz/admin", "/ready/../api/conversations", "/pings", "/api/ping/x",
     "/api/conversations", "/api/copilotkit"],
)
def test_exact_probe_exemption_does_not_widen(middleware, path, monkeypatch):
    monkeypatch.delenv("ALLOW_PUBLIC_COPILOT", raising=False)
    assert middleware.is_public_endpoint(path) is False
