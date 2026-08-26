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


def create_app() -> FastAPI:
    """Return the current canonical AI KAREN ASGI application.

    ``server.app`` currently constructs a compatibility module-level app during
    import. Returning that existing instance avoids invoking its factory a
    second time while the legacy composition package is being retired.
    New launchers must target this factory, never ``server.app`` directly.
    """

    from server import app as legacy_app

    return legacy_app.app
