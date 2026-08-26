"""Canonical FastAPI application entrypoint for AI KAREN.

All process launchers, containers, and deployment adapters must import the
application factory from this module. The root ``server`` package remains a
transitional composition implementation while its helpers and endpoint groups
are migrated by ownership.

This seam deliberately preserves the complete live application behavior until
the full composition cluster can move without dropping routes, lifecycle hooks,
health detail, RBAC checks, or observability behavior.
"""

from __future__ import annotations

from fastapi import FastAPI

from ai_karen_engine.api_routes.monitoring.probes import router as probe_router

_PROBES_REGISTERED_STATE_KEY = "_canonical_probe_routes_registered"


def create_app() -> FastAPI:
    """Return the current canonical AI KAREN ASGI application.

    ``server.app`` currently constructs a compatibility module-level app during
    import. Returning that existing instance avoids invoking its factory a
    second time while the legacy composition package is being retired.
    New launchers must target this factory, never ``server.app`` directly.

    Canonical liveness/readiness probes are attached here so deployment
    adapters do not depend on the transitional server package for probe
    semantics. Registration is idempotent because the compatibility app is a
    module-level singleton during this migration phase.
    """

    from server import app as legacy_app

    app = legacy_app.app
    if not getattr(app.state, _PROBES_REGISTERED_STATE_KEY, False):
        app.include_router(probe_router)
        setattr(app.state, _PROBES_REGISTERED_STATE_KEY, True)

    return app
