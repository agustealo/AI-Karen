"""Thin administrative API for Agent Medusa projections and run control."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ai_karen_engine.agent_medusa.control_plane import (
    AgentMedusaControlPlane,
    AgentNotFoundError,
    get_agent_control_plane,
)
from ai_karen_engine.agent_medusa.execution.run_manager import (
    RunNotCancellableError,
    RunNotFoundError,
    RunTenantMismatchError,
)
from ai_karen_engine.auth.rbac_middleware import Permission, require_permission

router = APIRouter(prefix="/admin/agents", tags=["admin-agents"])


def get_control_plane() -> AgentMedusaControlPlane:
    """Resolve the canonical Medusa administrative projection service."""

    return get_agent_control_plane()


def _tenant_id(current_user: dict[str, Any]) -> str:
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context is required for Medusa run access",
        )
    return str(tenant_id)


@router.get("")
async def list_agents(
    _current_user: dict[str, Any] = Depends(
        require_permission(Permission.ADMIN_RUNTIME_READ)
    ),
    control_plane: AgentMedusaControlPlane = Depends(get_control_plane),
):
    """Return the sanitized Agent Medusa administrative read model."""

    return await control_plane.list_agents()


@router.get("/runs")
async def list_runs(
    include_terminal: bool = Query(default=True),
    current_user: dict[str, Any] = Depends(
        require_permission(Permission.ADMIN_RUNTIME_READ)
    ),
    control_plane: AgentMedusaControlPlane = Depends(get_control_plane),
):
    """Return Medusa executions visible to the current tenant."""

    return await control_plane.list_runs(
        tenant_id=_tenant_id(current_user),
        include_terminal=include_terminal,
    )


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    current_user: dict[str, Any] = Depends(
        require_permission(Permission.ADMIN_RUNTIME_READ)
    ),
    control_plane: AgentMedusaControlPlane = Depends(get_control_plane),
):
    """Return one tenant-scoped Medusa execution."""

    try:
        return await control_plane.get_run(
            run_id=run_id,
            tenant_id=_tenant_id(current_user),
        )
    except (RunNotFoundError, RunTenantMismatchError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Medusa run not found",
        ) from exc


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    current_user: dict[str, Any] = Depends(
        require_permission(Permission.ADMIN_RUNTIME_MANAGE)
    ),
    control_plane: AgentMedusaControlPlane = Depends(get_control_plane),
):
    """Cancel the actual coordinator task for one tenant-scoped run."""

    try:
        return await control_plane.cancel_run(
            run_id=run_id,
            tenant_id=_tenant_id(current_user),
        )
    except (RunNotFoundError, RunTenantMismatchError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Medusa run not found",
        ) from exc
    except RunNotCancellableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    _current_user: dict[str, Any] = Depends(
        require_permission(Permission.ADMIN_RUNTIME_READ)
    ),
    control_plane: AgentMedusaControlPlane = Depends(get_control_plane),
):
    """Return one sanitized Agent Medusa administrative projection."""

    try:
        return await control_plane.get_agent(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
