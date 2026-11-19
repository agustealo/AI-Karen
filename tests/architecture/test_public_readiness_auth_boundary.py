"""Canonical public readiness must not require a user session.

This is a narrow transport/probe exemption. Private routes continue to use
the normal authenticated-request boundary and readiness cannot be forged.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from ai_karen_engine.api_routes.monitoring.probes import router as probe_router
from ai_karen_engine.auth.auth_middleware import SecureAuthMiddleware
from ai_karen_engine.server import routers as registry


def test_exact_readiness_is_public_but_adjacent_paths_are_private() -> None:
    # Avoid initializing JWT, Redis, or an external database for path policy.
    auth = object.__new__(SecureAuthMiddleware)

    assert auth.is_public_endpoint("/ready") is True
    for path in ("/ready/admin", "/readiness", "/api/ready", "/private", "/api/conversations"):
        assert auth.is_public_endpoint(path) is False
    assert auth.is_public_endpoint("/health/live") is True


def test_auth_boundary_allows_anonymous_readiness_not_private_routes(monkeypatch) -> None:
    class RejectingAuth:
        def is_public_endpoint(self, path: str) -> bool:
            return SecureAuthMiddleware.is_public_endpoint(self, path)

        async def authenticate_request(self, request):
            raise HTTPException(status_code=401, detail="Authentication required")

    monkeypatch.setattr(registry, "get_auth_middleware", lambda: RejectingAuth())
    monkeypatch.setattr(registry.auth_config, "should_bypass_auth", lambda: False)

    app = FastAPI()
    app.state.settings = object()
    app.state.database_available = True
    registry.configure_authentication_middleware(app)
    app.include_router(probe_router)

    @app.get("/private")
    async def private():
        return {"secret": "only authenticated users"}

    @app.get("/ready/admin")
    async def private_ready():
        return {"secret": "not a public probe"}

    with TestClient(app) as client:
        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["ready"] is True
        assert ready.json()["components"] == {
            "configuration": "ready",
            "database": "ready",
        }

        assert client.get("/health/live").status_code == 200
        assert client.get("/private").status_code == 401
        assert client.get("/ready/admin").status_code == 401

        # Public does not mean always healthy. Keep actual dependency gating.
        app.state.database_available = False
        unavailable = client.get("/ready")
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"]["components"]["database"] == "unavailable"
