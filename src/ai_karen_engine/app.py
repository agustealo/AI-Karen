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
_LEGACY_SHUTDOWN_HANDLER_NAMES = frozenset(
    {
        "_shutdown_database",
        "shutdown_extension_health_monitoring",
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

    if not getattr(app.state, _PROBES_REGISTERED_STATE_KEY, False):
        app.include_router(probe_router)
        setattr(app.state, _PROBES_REGISTERED_STATE_KEY, True)

    if not getattr(app.state, _METRICS_REGISTERED_STATE_KEY, False):
        app.include_router(metrics_router)
        setattr(app.state, _METRICS_REGISTERED_STATE_KEY, True)

    return app
