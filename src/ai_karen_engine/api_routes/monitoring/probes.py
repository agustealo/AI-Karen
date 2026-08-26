from __future__ import annotations

"""Canonical process liveness and application readiness probes.

These probes intentionally stay small. They do not duplicate provider health,
extension diagnostics, degraded-mode reporting, or detailed infrastructure
observability. Detailed health remains available through the monitoring health
router; these endpoints answer only whether the process is alive and whether
the application has completed the minimum required startup state to serve
production traffic.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["system"])


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/health/live")
async def liveness_probe() -> Dict[str, Any]:
    """Return process liveness without probing downstream dependencies."""

    return {
        "status": "alive",
        "timestamp": _timestamp(),
    }


@router.get("/ready")
async def readiness_probe(request: Request) -> Dict[str, Any]:
    """Return readiness for production traffic.

    PostgreSQL is a required production dependency for authenticated state,
    persistence, tenant-scoped data, and durable memory. Optional model
    providers and extension capabilities are deliberately excluded from the
    readiness gate so their failure can be represented through KAREN's normal
    degraded-mode metadata rather than causing an application restart loop.
    """

    settings_loaded = getattr(request.app.state, "settings", None) is not None
    database_available = bool(
        getattr(request.app.state, "database_available", False)
    )

    components = {
        "configuration": "ready" if settings_loaded else "unavailable",
        "database": "ready" if database_available else "unavailable",
    }
    ready = settings_loaded and database_available

    payload: Dict[str, Any] = {
        "ready": ready,
        "status": "ready" if ready else "not_ready",
        "components": components,
        "timestamp": _timestamp(),
    }

    if not ready:
        raise HTTPException(status_code=503, detail=payload)

    return payload
