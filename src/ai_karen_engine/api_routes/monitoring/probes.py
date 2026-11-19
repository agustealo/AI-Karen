from __future__ import annotations

"""Canonical process liveness and application readiness probes.

These probes intentionally stay small. They do not duplicate provider health,
extension diagnostics, degraded-mode reporting, or detailed infrastructure
observability. Detailed health remains available through the monitoring health
router; these endpoints answer only whether the process is alive, whether the
application has completed the minimum required startup state to serve
production traffic, and the two historical ping aliases used for connectivity
checks.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from ai_karen_engine.core.runtime.operational_health import get_operational_health_service

router = APIRouter(tags=["system"])


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ping_payload() -> Dict[str, Any]:
    return {
        "status": "ok",
        "timestamp": _timestamp(),
    }


@router.get("/ping")
async def root_ping() -> Dict[str, Any]:
    """Historical root connectivity alias."""

    return _ping_payload()


@router.get("/api/ping")
async def api_ping() -> Dict[str, Any]:
    """Historical API connectivity alias."""

    return _ping_payload()


@router.get("/health/live")
async def liveness_probe() -> Dict[str, Any]:
    """Return process liveness without probing downstream dependencies."""

    return {
        "status": "alive",
        "timestamp": _timestamp(),
    }


@router.get("/ready")
async def readiness_probe(request: Request) -> Dict[str, Any]:
    """Delegate readiness to the single runtime dependency authority.

    The public probe must never infer readiness from the existence of settings
    and PostgreSQL alone: Redis-backed memory and rate limiting can be required.
    This route only translates the runtime's result to HTTP status.
    """
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(
            status_code=503,
            detail={
                "ready": False,
                "status": "not_ready",
                "components": {"configuration": "not_ready", "database": "not_ready"},
            },
        )
    result = await get_operational_health_service().readiness(
        environment=str(getattr(settings, "environment", "production")),
    )
    payload = result.as_dict()
    if not result.ready:
        raise HTTPException(status_code=503, detail=payload)
    return payload
