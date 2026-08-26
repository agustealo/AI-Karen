"""Compatibility shim for retired root-server health registration.

Canonical connectivity probes live in
``ai_karen_engine.api_routes.monitoring.probes`` and detailed health lives in
``ai_karen_engine.api_routes.monitoring.health``.

This module owns no routes and no health logic. It exists only because the
transitional ``server.app`` composition root still imports
``register_health_endpoints``. Delete this shim together with that import/call
when ``server.app`` is reduced to a compatibility composition layer.
"""

from __future__ import annotations

from fastapi import FastAPI


def register_health_endpoints(app: FastAPI) -> None:
    """Preserve the legacy composition call without registering any routes."""

    del app
