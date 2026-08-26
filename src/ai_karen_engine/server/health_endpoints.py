from __future__ import annotations

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from ai_karen_engine.api_routes.monitoring.health import router as health_router
from ai_karen_engine.core.runtime.operational_health import (
    get_operational_health_service,
)

operational_router = APIRouter(prefix="/health", tags=["system"])


@operational_router.get("/live")
async def liveness_probe() -> dict:
    """Return process liveness without dependency fan-out."""
    return get_operational_health_service().liveness()


@operational_router.get("/ready")
async def readiness_probe(request: Request):
    """Return 200 only when production-critical runtime requirements are ready."""
    settings = request.app.state.settings
    result = await get_operational_health_service().readiness(
        environment=settings.environment,
    )
    payload = result.as_dict()
    if result.ready:
        return payload
    return JSONResponse(status_code=503, content=payload)


def register_health_endpoints(app: FastAPI) -> None:
    """Register the canonical detailed and operational health endpoints."""
    app.include_router(operational_router)
    app.include_router(health_router)


__all__ = ["register_health_endpoints"]
