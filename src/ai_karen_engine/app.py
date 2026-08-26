"""Canonical FastAPI application entrypoint for AI KAREN.

All process launchers, containers, and deployment adapters must import the
application factory from this module.  The implementation still delegates to
the legacy root ``server`` package while SERVER-CONVERGE migrates composition
responsibilities into ``ai_karen_engine``.  Keeping this seam stable prevents
launchers from depending on that migration layout.

This module owns no provider selection, prompt construction, memory recall,
plugin execution, persistence, or other runtime behavior.
"""

from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Create the canonical AI KAREN ASGI application.

    ``server.app`` is a temporary implementation detail.  New callers must use
    this factory so the legacy package can be retired without changing the
    deployment contract.
    """

    from server.app import create_app as create_legacy_app

    return create_legacy_app()
