"""Thin read-only administrative API for Agent Medusa projections."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from ai_karen_engine.agent_medusa.control_plane import (
    AgentMedusaControlPlane,
    AgentNotFoundError,
    get_agent_control_plane,
)
from ai_karen_engine.auth.rbac_middleware import Permission, require_permission

router = APIRouter(prefix="/admin/agents", tags=["admin-agents"])


def get_control_plane() -> AgentMedusaControlPlane:
    """Resolve the canonical Medusa administrative projection service."""

    return get_agent_control_plane()


@router.get("")
async def list_agents(
    _current_user: dict[str, Any] = Depends(
        require_permission(Permission.ADMIN_RUNTIME_READ)
    ),
    control_plane: AgentMedusaControlPlane = Depends(get_control_plane),
):
    """Return the sanitized Agent Medusa administrative read model."""

    return await control_plane.list_agents()


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
