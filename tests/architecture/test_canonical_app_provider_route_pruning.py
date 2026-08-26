from __future__ import annotations

from fastapi import FastAPI

from ai_karen_engine.app import _prune_legacy_provider_routes


LEGACY_MODULE = "ai_karen_engine.api_routes.models.management"
CANONICAL_MODULE = "ai_karen_engine.api_routes.models.providers"


def _endpoint(module_name: str):
    async def endpoint() -> dict[str, bool]:
        return {"ok": True}

    endpoint.__module__ = module_name
    return endpoint


def test_prunes_only_legacy_provider_shadow_routes() -> None:
    app = FastAPI()

    app.add_api_route(
        "/api/providers",
        _endpoint(LEGACY_MODULE),
        methods=["GET"],
    )
    app.add_api_route(
        "/api/providers/stats",
        _endpoint(LEGACY_MODULE),
        methods=["GET"],
    )
    app.add_api_route(
        "/api/providers/",
        _endpoint(CANONICAL_MODULE),
        methods=["GET"],
    )
    app.add_api_route(
        "/api/providers/discovery",
        _endpoint(CANONICAL_MODULE),
        methods=["GET"],
    )
    app.add_api_route(
        "/api/models/local",
        _endpoint(LEGACY_MODULE),
        methods=["GET"],
    )

    _prune_legacy_provider_routes(app)

    remaining = {
        (getattr(route, "path", None), getattr(route.endpoint, "__module__", None))
        for route in app.router.routes
        if hasattr(route, "endpoint")
    }

    assert ("/api/providers", LEGACY_MODULE) not in remaining
    assert ("/api/providers/stats", LEGACY_MODULE) not in remaining
    assert ("/api/providers/", CANONICAL_MODULE) in remaining
    assert ("/api/providers/discovery", CANONICAL_MODULE) in remaining
    assert ("/api/models/local", LEGACY_MODULE) in remaining


def test_provider_route_pruning_is_idempotent() -> None:
    app = FastAPI()
    app.add_api_route(
        "/api/providers/profiles",
        _endpoint(LEGACY_MODULE),
        methods=["GET"],
    )

    _prune_legacy_provider_routes(app)
    first_routes = list(app.router.routes)

    _prune_legacy_provider_routes(app)

    assert app.router.routes == first_routes
    assert getattr(app.state, "_legacy_provider_routes_pruned", False) is True
