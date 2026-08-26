from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ai_karen_engine.auth.rbac_middleware import Permission, require_permission
from ai_karen_engine.platform.observability.diagnostics_service import (
    DiagnosticsService,
    RequestTrace,
    get_diagnostics_service,
)

router = APIRouter(prefix="/admin/diagnostics", tags=["admin-diagnostics"])


class ScorecardResponse(BaseModel):
    scorecard: dict[str, Any]
    buffered_events: int


class ProviderBreakdownResponse(BaseModel):
    providers: list[dict[str, Any]]


def _service() -> DiagnosticsService:
    return get_diagnostics_service()


@router.get("/summary", response_model=ScorecardResponse)
async def get_diagnostics_summary(
    current_user: dict[str, Any] = Depends(require_permission(Permission.ADMIN_RUNTIME_READ)),  # noqa: B008
    service: DiagnosticsService = Depends(_service),  # noqa: B008
):
    """Operational scorecard summary derived from the diagnostics buffer."""
    return service.summary()


@router.get("/events")
async def get_diagnostics_events(
    correlation_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    plugin: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    current_user: dict[str, Any] = Depends(require_permission(Permission.ADMIN_RUNTIME_READ)),  # noqa: B008
    service: DiagnosticsService = Depends(_service),  # noqa: B008
):
    """Recent operational events with bounded filters (admin/runtime read)."""
    return {
        "events": service.recent_events(
            correlation_id=correlation_id,
            event_type=event_type,
            status=status,
            provider=provider,
            plugin=plugin,
            limit=limit,
        )
    }


@router.get("/requests")
async def get_request_traces(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict[str, Any] = Depends(require_permission(Permission.ADMIN_RUNTIME_READ)),  # noqa: B008
    service: DiagnosticsService = Depends(_service),  # noqa: B008
):
    """Reconstructed request traces showing per-stage timing."""
    traces: list[RequestTrace] = service.request_traces(limit=limit)
    return {
        "traces": [
            {
                "request_id": t.request_id,
                "correlation_id": t.correlation_id,
                "total_duration_ms": t.total_duration_ms,
                "status": t.status,
                "stages": t.stages,
            }
            for t in traces
        ]
    }


@router.get("/providers", response_model=ProviderBreakdownResponse)
async def get_diagnostics_providers(
    current_user: dict[str, Any] = Depends(require_permission(Permission.ADMIN_PROVIDERS_READ)),  # noqa: B008
    service: DiagnosticsService = Depends(_service),  # noqa: B008
):
    """Provider request/failure/fallback breakdown from the buffer."""
    return ProviderBreakdownResponse(providers=service.provider_breakdown())
