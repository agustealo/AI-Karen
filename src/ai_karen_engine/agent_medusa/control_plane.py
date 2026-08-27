"""Backend-authoritative administrative projection for Agent Medusa.

Agent Medusa specialists are execution-scoped, not daemon processes. The
coordinator currently owns per-execution lifecycle objects, so an unrelated
admin lifecycle object would create false start/stop/restart state. This module
therefore exposes only registry and health truth until lifecycle observation
and cancellation are centralized in the runtime.

Prompt contracts, provider selection, tools/plugins, runtime config, approval
rules, and executable objects are intentionally excluded from the UI contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .contracts.registration import AgentRegistration
from .registry import MedusaRegistry, get_medusa_registry


class AgentControlError(RuntimeError):
    """Base administrative agent projection error."""

    code = "agent_control_error"


class AgentNotFoundError(AgentControlError):
    """Raised when an administrative projection references an unknown agent."""

    code = "agent_not_found"


class AgentMedusaControlPlane:
    """Canonical sanitized administrative read model for Agent Medusa."""

    def __init__(self, *, registry: MedusaRegistry | None = None) -> None:
        self._registry = registry or get_medusa_registry()

    async def initialize(self) -> None:
        """Initialize the canonical registry without fabricating runtime state."""

        await self._registry.initialize()

    async def list_agents(self) -> dict[str, Any]:
        """Return sanitized projections for every registered Medusa agent."""

        await self.initialize()
        registrations = await self._registry.list_agents()
        agents = [
            await self._project_registration(registration)
            for registration in registrations
        ]
        return {
            "agents": agents,
            "total": len(agents),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_agent(self, agent_id: str) -> dict[str, Any]:
        """Return one sanitized administrative projection."""

        await self.initialize()
        registration = await self._registry.get_agent(agent_id)
        if registration is None:
            raise AgentNotFoundError(f"Unknown agent: {agent_id}")
        return await self._project_registration(registration)

    async def _project_registration(
        self,
        registration: AgentRegistration,
    ) -> dict[str, Any]:
        health = await self._registry.get_agent_health(registration.agent_id)
        capabilities = [
            {
                "type": getattr(capability.type, "value", str(capability.type)),
                "name": capability.name,
                "description": capability.description,
            }
            for capability in registration.capabilities
        ]
        healthy = bool(health.get("healthy", True))
        return {
            "agent_id": registration.agent_id,
            "name": registration.name,
            "description": registration.description,
            "version": registration.version,
            "definition_state": registration.lifecycle_state,
            "catalog_status": registration.status,
            "health_status": "healthy" if healthy else "degraded",
            "healthy": healthy,
            "missing_dependencies": list(health.get("missing_dependencies", [])),
            "capabilities": capabilities,
            "runtime_control": {
                "supported": False,
                "reason_code": "specialist_lifecycle_is_execution_scoped",
            },
            "registered_at": registration.registered_at.isoformat(),
        }


_control_plane: AgentMedusaControlPlane | None = None


def get_agent_control_plane() -> AgentMedusaControlPlane:
    """Return the process-wide Medusa administrative projection service."""

    global _control_plane
    if _control_plane is None:
        _control_plane = AgentMedusaControlPlane()
    return _control_plane


__all__ = [
    "AgentControlError",
    "AgentMedusaControlPlane",
    "AgentNotFoundError",
    "get_agent_control_plane",
]
