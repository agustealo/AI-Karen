"""Canonical FastAPI application entrypoint for AI KAREN.

All process launchers, containers, and deployment adapters must import the
application factory from this module. The root ``server`` package remains a
transitional composition implementation while its helpers and endpoint groups
are migrated by ownership.

This seam deliberately preserves the complete live application behavior until
the full composition cluster can move without dropping routes, lifecycle hooks,
RBAC checks, or observability behavior. Legacy health routes are pruned here so
only canonical monitoring/probe authorities are reachable during the remaining
server-package source cleanup.
"""

from __future__ import annotations

from fastapi import FastAPI

from ai_karen_engine.api_routes.monitoring.probes import router as probe_router

_PROBES_REGISTERED_STATE_KEY = "_canonical_probe_routes_registered"
_LEGACY_HEALTH_PRUNED_STATE_KEY = "_legacy_inline_health_routes_pruned"
_LEGACY_INLINE_HEALTH_PATHS = frozenset(
    {
        "/health",
        "/api/health/database",
        "/api/health/database/test",
        "/api/health/database/monitor",
        "/api/health/degraded-mode",
    }
)


def _prune_legacy_inline_health_routes(app: FastAPI) -> None:
    """Remove transitional health handlers defined directly by ``server.app``.

    Detailed health is owned by ``api_routes.monitoring.health`` and deployment
    probes are owned by ``api_routes.monitoring.probes``. The source blocks are
    temporarily left in the legacy composition module to avoid a risky whole-file
    rewrite while other server migration work is active, but they must not remain
    reachable at runtime.
    """

    if getattr(app.state, _LEGACY_HEALTH_PRUNED_STATE_KEY, False):
        return

    retained_routes = []
    for route in app.router.routes:
        path = getattr(route, "path", None)
        endpoint = getattr(route, "endpoint", None)
        endpoint_module = getattr(endpoint, "__module__", None)
        is_legacy_health = (
            path in _LEGACY_INLINE_HEALTH_PATHS and endpoint_module == "server.app"
        )
        if not is_legacy_health:
            retained_routes.append(route)

    app.router.routes[:] = retained_routes
    setattr(app.state, _LEGACY_HEALTH_PRUNED_STATE_KEY, True)


def create_app() -> FastAPI:
    """Return the current canonical AI KAREN ASGI application.

    ``server.app`` currently constructs a compatibility module-level app during
    import. Returning that existing instance avoids invoking its factory a
    second time while the legacy composition package is being retired.
    New launchers must target this factory, never ``server.app`` directly.

    Canonical liveness/readiness probes are attached here so deployment
    adapters do not depend on the transitional server package for probe
    semantics. Registration and legacy route pruning are idempotent because the
    compatibility app is a module-level singleton during this migration phase.
    """

    from server import app as legacy_app

    app = legacy_app.app
    _prune_legacy_inline_health_routes(app)

    if not getattr(app.state, _PROBES_REGISTERED_STATE_KEY, False):
        app.include_router(probe_router)
        setattr(app.state, _PROBES_REGISTERED_STATE_KEY, True)

    return app
