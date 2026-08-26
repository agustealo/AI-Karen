"""Canonical FastAPI application entrypoint for AI KAREN.

All process launchers, containers, and deployment adapters must import the
application factory from this module. The root ``server`` package remains a
transitional composition implementation while its helpers and endpoint groups
are migrated by ownership.

Health, readiness, and metrics exposition are owned by canonical monitoring
routers. Canonical lifespan owns database cleanup; transitional duplicate
shutdown callbacks from ``server.app`` are removed here until that composition
source is physically retired.
"""

from __future__ import annotations

from fastapi import FastAPI

from ai_karen_engine.api_routes.monitoring.metrics import router as metrics_router
from ai_karen_engine.api_routes.monitoring.probes import router as probe_router

_PROBES_REGISTERED_STATE_KEY = "_canonical_probe_routes_registered"
_METRICS_REGISTERED_STATE_KEY = "_canonical_metrics_routes_registered"
_LEGACY_SHUTDOWN_PRUNED_STATE_KEY = "_legacy_shutdown_handlers_pruned"
_LEGACY_PROVIDER_ROUTES_PRUNED_STATE_KEY = "_legacy_provider_routes_pruned"
_LEGACY_SHUTDOWN_HANDLER_NAMES = frozenset(
    {
        "_shutdown_database",
        "shutdown_extension_health_monitoring",
    }
)
_LEGACY_PROVIDER_ENDPOINT_MODULE = "ai_karen_engine.api_routes.models.management"
_LEGACY_PROVIDER_ROUTE_PATHS = frozenset(
    {
        "/api/providers",
        "/api/providers/profiles",
        "/api/providers/profiles/active",
        "/api/providers/stats",
    }
)


def _prune_legacy_shutdown_handlers(app: FastAPI) -> None:
    """Remove duplicate shutdown callbacks still defined by ``server.app``.

    The canonical lifespan owns database cleanup. Matching both the exact
    callback name and legacy module keeps canonical lifecycle handlers intact.
    """

    if getattr(app.state, _LEGACY_SHUTDOWN_PRUNED_STATE_KEY, False):
        return

    retained_handlers = []
    for handler in app.router.on_shutdown:
        handler_module = getattr(handler, "__module__", None)
        handler_name = getattr(handler, "__name__", None)
        is_legacy_duplicate = (
            handler_module == "server.app"
            and handler_name in _LEGACY_SHUTDOWN_HANDLER_NAMES
        )
        if not is_legacy_duplicate:
            retained_handlers.append(handler)

    app.router.on_shutdown[:] = retained_handlers
    setattr(app.state, _LEGACY_SHUTDOWN_PRUNED_STATE_KEY, True)


def _prune_legacy_provider_routes(app: FastAPI) -> None:
    """Quarantine provider-shadow routes owned by legacy model management.

    ``api_routes.models.providers`` is the canonical provider ingress and is
    already wired by ``server.routers`` before the transitional model-management
    router. The legacy management module still defines mock/fallback provider
    endpoints that can expose fabricated provider health, profiles, and stats.
    Remove only those shadow routes here while the mega-router is being split.

    Matching both module and path prevents accidental removal of canonical or
    third-party routes that happen to use similar URLs.
    """

    if getattr(app.state, _LEGACY_PROVIDER_ROUTES_PRUNED_STATE_KEY, False):
        return

    retained_routes = []
    for route in app.router.routes:
        endpoint = getattr(route, "endpoint", None)
        endpoint_module = getattr(endpoint, "__module__", None)
        path = getattr(route, "path", None)
        is_legacy_provider_shadow = (
            endpoint_module == _LEGACY_PROVIDER_ENDPOINT_MODULE
            and path in _LEGACY_PROVIDER_ROUTE_PATHS
        )
        if not is_legacy_provider_shadow:
            retained_routes.append(route)

    app.router.routes[:] = retained_routes
    setattr(app.state, _LEGACY_PROVIDER_ROUTES_PRUNED_STATE_KEY, True)


def create_app() -> FastAPI:
    """Return the current canonical AI KAREN ASGI application.

    ``server.app`` currently constructs a compatibility module-level app during
    import. Returning that existing instance avoids invoking its factory a
    second time while the legacy composition package is being retired.
    New launchers must target this factory, never ``server.app`` directly.

    Canonical connectivity, liveness, readiness, and metrics routes are
    attached here. Registration and lifecycle pruning are idempotent because
    the compatibility app remains a module-level singleton during migration.
    """

    from server import app as legacy_app

    app = legacy_app.app
    _prune_legacy_shutdown_handlers(app)
    _prune_legacy_provider_routes(app)

    if not getattr(app.state, _PROBES_REGISTERED_STATE_KEY, False):
        app.include_router(probe_router)
        setattr(app.state, _PROBES_REGISTERED_STATE_KEY, True)

    if not getattr(app.state, _METRICS_REGISTERED_STATE_KEY, False):
        app.include_router(metrics_router)
        setattr(app.state, _METRICS_REGISTERED_STATE_KEY, True)

    return app
