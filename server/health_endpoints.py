"""Legacy connectivity aliases for the transitional root server package.

Detailed health ownership lives in
``ai_karen_engine.api_routes.monitoring.health``. Process liveness and traffic
readiness live in ``ai_karen_engine.api_routes.monitoring.probes``.

This module intentionally retains only the historical ping aliases while the
root ``server`` package is being retired. It must not register health,
readiness, provider, database, Redis, system-resource, or extension-recovery
routes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI


def _ping_payload() -> dict[str, str]:
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def register_health_endpoints(app: FastAPI) -> None:
    """Register compatibility ping aliases only.

    ``/health/live`` and ``/ready`` are canonical deployment probes. Detailed
    monitoring is registered through the canonical monitoring router. Keeping
    those responsibilities out of this compatibility module prevents route
    ordering from silently choosing between competing health implementations.
    """

    @app.get("/api/ping", tags=["system"], include_in_schema=False)
    async def api_ping() -> dict[str, str]:
        return _ping_payload()

    @app.get("/ping", tags=["system"], include_in_schema=False)
    async def root_ping() -> dict[str, str]:
        return _ping_payload()
