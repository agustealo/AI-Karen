"""Exact anonymous /ready authorization across the canonical ASGI boundary.

Execute the actual registered auth middleware implementation while avoiding
imports of unrelated app routers (training, plugins, models). This test runs
with the lean Main Quality dependency set.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from ai_karen_engine.api_routes.monitoring.probes import router as probe_router
from ai_karen_engine.auth.auth_middleware import SecureAuthMiddleware


ROOT = Path(__file__).resolve().parents[2]
ROUTERS = ROOT / "src/ai_karen_engine/server/routers.py"


def _canonical_auth_configuration(rejecting_auth):
    """Compile the real app middleware function, not its heavy router imports."""
    source = ROUTERS.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(ROUTERS))
    owned = [
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"_http_error", "configure_authentication_middleware"}
    ]
    assert len(owned) == 2
    source_module = ast.Module(body=owned, type_ignores=[])
    ast.fix_missing_locations(source_module)

    class UnusedAuthError(Exception):
        status_code = 401
        message = "Authentication required"

    class UnusedDevConfigError(Exception):
        pass

    scope = {
        "Any": Any,
        "FastAPI": FastAPI,
        "Request": Request,
        "HTTPException": HTTPException,
        "JSONResponse": JSONResponse,
        "get_auth_middleware": lambda: rejecting_auth,
        "auth_config": SimpleNamespace(should_bypass_auth=lambda: False),
        "AuthenticationError": UnusedAuthError,
        "DevelopmentIdentityConfigurationError": UnusedDevConfigError,
        "is_native_channel_webhook_path": lambda *_: False,
        "is_personal_pairing_callback_path": lambda *_: False,
        "logger": logging.getLogger("test.public_readiness"),
    }
    exec(compile(source_module, str(ROUTERS), "exec"), scope)
    return scope["configure_authentication_middleware"]


def test_exact_readiness_is_public_but_adjacent_paths_are_private() -> None:
    # No JWT, Redis, training or database initialization required for path policy.
    auth = object.__new__(SecureAuthMiddleware)
    assert auth.is_public_endpoint("/ready") is True
    for path in (
        "/ready/admin", "/readiness", "/api/ready",
        "/private", "/api/conversations",
    ):
        assert auth.is_public_endpoint(path) is False
    assert auth.is_public_endpoint("/health/live") is True


def test_auth_boundary_allows_anonymous_readiness_not_private_routes() -> None:
    class RejectingAuth:
        def is_public_endpoint(self, path: str) -> bool:
            return SecureAuthMiddleware.is_public_endpoint(self, path)

        async def authenticate_request(self, request: Request):
            raise HTTPException(status_code=401, detail="Authentication required")

    app = FastAPI()
    app.state.settings = object()
    app.state.database_available = True
    _canonical_auth_configuration(RejectingAuth())(app)
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

        # Being public never manufactures readiness when PostgreSQL is down.
        app.state.database_available = False
        unavailable = client.get("/ready")
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"]["components"]["database"] == "unavailable"
