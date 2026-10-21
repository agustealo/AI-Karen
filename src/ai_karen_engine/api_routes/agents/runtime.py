"""Read-only consumer projection for the canonical Agent Medusa catalog.

This route exposes registered specialist truth for authenticated users without
creating a second execution path. CORTEX and RuntimePolicy still decide whether
an agent is eligible for a specific chat request; ChatRuntime remains the only
consumer execution authority.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.agent_medusa.control_plane import AgentMedusaControlPlane, get_agent_control_plane

from ai_karen_engine.agent_medusa.service import (
    AgentMedusaService,
    get_agent_medusa_service,
)
from ai_karen_engine.core.services.dependencies import bypass_user_context_func

router = APIRouter(prefix="/api/agent-runtime", tags=["agent-runtime"])


def get_service() -> AgentMedusaService:
    """Resolve the canonical Medusa service."""

    return get_agent_medusa_service()


@router.get("/catalog")
async def get_agent_catalog(
    _current_user: Dict[str, Any] = Depends(bypass_user_context_func),
    service: AgentMedusaService = Depends(get_service),
) -> Dict[str, Any]:
    """Return registered active specialists without claiming request eligibility."""

    agents = await service.list_agent_catalog()
    return {
        "agents": [
            {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "description": agent.description,
                "version": agent.version,
                "lifecycle_state": agent.lifecycle_state,
                "status": agent.status,
                "capabilities": list(agent.capabilities),
                "implementation_id": agent.implementation_id,
                "prompt_contract_id": agent.prompt_contract_id,
                "prompt_version": agent.prompt_version,
                "healthy": agent.healthy,
                "missing_dependencies": list(agent.missing_dependencies),
                "eligibility": "runtime_decided_per_request",
            }
            for agent in agents
        ],
        "total": len(agents),
        "selection_authority": "cortex_runtime_policy",
        "execution_authority": "chat_runtime",
        "orchestrator": "agent_medusa",
    }


__all__ = ["router"]


def get_run_control_plane() -> AgentMedusaControlPlane:
    """Reuse Medusa's existing run projection; never create separate run storage."""
    return get_agent_control_plane()


@router.get("/my-runs")
async def list_my_agent_runs(
    current_user: UserData = Depends(get_current_user),
    control_plane: AgentMedusaControlPlane = Depends(get_run_control_plane),
) -> Dict[str, Any]:
    """Return only authenticated user's tenant-scoped Medusa runs.

    Filtering occurs on the server, never from client-provided user IDs.
    This is a consumer read projection, not administrative run control.
    """
    tenant_id = str(current_user.tenant_id or "").strip()
    owner_id = str(current_user.user_id or "").strip()
    if not current_user.is_active or not owner_id or not tenant_id or tenant_id == "default":
        raise HTTPException(status_code=403, detail="Verified active user and tenant required")
    result = await control_plane.list_runs(tenant_id=tenant_id, include_terminal=True, user_id=owner_id)
    owned = [run for run in result["runs"] if str(run.get("user_id") or "") == owner_id]
    return {
        "runs": owned,
        "total": len(owned),
        "generated_at": result["generated_at"],
    }


@router.get("/my-runs/{run_id}")
async def get_my_agent_run(
    run_id: str,
    current_user: UserData = Depends(get_current_user),
    control_plane: AgentMedusaControlPlane = Depends(get_run_control_plane),
) -> Dict[str, Any]:
    """Resolve a selected run using authoritative tenant + owner constraints.

    A user-provided run ID is only a lookup key. Ownership is established
    independently by the canonical Medusa run record before returning details.
    """
    tenant_id = str(current_user.tenant_id or "").strip()
    owner_id = str(current_user.user_id or "").strip()
    if not current_user.is_active or not owner_id or not tenant_id or tenant_id == "default":
        raise HTTPException(status_code=403, detail="Verified active user and tenant required")
    if not run_id or len(run_id) > 128:
        raise HTTPException(status_code=404, detail="Execution not found")
    from ai_karen_engine.agent_medusa.execution.run_manager import (
        RunNotFoundError, RunTenantMismatchError,
    )
    try:
        record = await control_plane.get_run(run_id=run_id, tenant_id=tenant_id)
    except (RunNotFoundError, RunTenantMismatchError) as exc:
        raise HTTPException(status_code=404, detail="Execution not found") from exc
    if str(record.get("user_id") or "") != owner_id:
        raise HTTPException(status_code=404, detail="Execution not found")
    return record


@router.get("/my-runs/{run_id}/context")
async def get_my_run_context(
    run_id: str,
    current_user: UserData = Depends(get_current_user),
    control_plane: AgentMedusaControlPlane = Depends(get_run_control_plane),
) -> Dict[str, Any]:
    """Return a minimal, owner-verified reference for conversational follow-up.

    This is evidence for a user-facing question, not an authorization grant for
    ChatRuntime tools. Runtime must independently verify any subsequent action.
    """
    record = await get_my_agent_run(
        run_id, current_user=current_user, control_plane=control_plane
    )
    return {
        "resource_type": "medusa_run",
        "run_id": record["run_id"],
        "status": record["status"],
        "started_at": record.get("started_at"),
        "completed_at": record.get("completed_at"),
        "error_type": record.get("error_type"),
    }
