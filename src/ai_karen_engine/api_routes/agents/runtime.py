"""Read-only consumer projection for the canonical Agent Medusa catalog.

This route exposes registered specialist truth for authenticated users without
creating a second execution path. CORTEX and RuntimePolicy still decide whether
an agent is eligible for a specific chat request; ChatRuntime remains the only
consumer execution authority.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

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
