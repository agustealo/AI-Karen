"""Backend-authoritative administrative projection for Agent Medusa.

Agent definitions remain registry-owned and execution-scoped. Per-agent daemon
start/stop controls are intentionally absent. Actual coordinator request tasks
are governed by the process-wide MedusaRunManager and can be observed or
cancelled by concrete run id with tenant isolation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ai_karen_engine.audit_logging import (
    AuditEvent,
    AuditEventType,
    AuditLogger,
    AuditSeverity,
    get_audit_logger,
)

from .contracts.registration import AgentRegistration
from .execution.run_manager import (
    MedusaRunManager,
    get_medusa_run_manager,
)
from .registry import MedusaRegistry, get_medusa_registry


class AgentControlError(RuntimeError):
    """Base administrative agent projection error."""

    code = "agent_control_error"


class AgentNotFoundError(AgentControlError):
    """Raised when an administrative projection references an unknown agent."""

    code = "agent_not_found"


class AgentMedusaControlPlane:
    """Canonical sanitized administrative read/control model for Agent Medusa."""

    def __init__(
        self,
        *,
        registry: MedusaRegistry | None = None,
        run_manager: MedusaRunManager | None = None,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self._registry = registry or get_medusa_registry()
        self._run_manager = run_manager or get_medusa_run_manager()
        self._audit_logger = audit_logger or get_audit_logger()

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

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool = True,
    ) -> dict[str, Any]:
        """Return tenant-scoped execution run snapshots."""

        runs = await self._run_manager.list_runs(
            tenant_id=tenant_id,
            include_terminal=include_terminal,
        )
        return {
            "runs": runs,
            "total": len(runs),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_run(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        """Return one tenant-scoped execution run snapshot."""

        return await self._run_manager.get(run_id=run_id, tenant_id=tenant_id)

    async def cancel_run(
        self,
        *,
        run_id: str,
        tenant_id: str,
        actor_user_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Request cancellation and audit the runtime-owned side effect."""

        result = await self._run_manager.cancel(run_id=run_id, tenant_id=tenant_id)
        distributed = result.get("distributed_control")
        self._audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.SYSTEM_EVENT,
                severity=AuditSeverity.INFO,
                message="medusa_run_cancel_requested",
                user_id=actor_user_id,
                tenant_id=tenant_id,
                session_id=session_id,
                correlation_id=str(result.get("correlation_id") or run_id),
                metadata={
                    "run_id": run_id,
                    "resulting_status": result.get("status"),
                    "distributed_control_supported": (
                        distributed.get("supported")
                        if isinstance(distributed, dict)
                        else False
                    ),
                },
            )
        )
        return result

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
                "reason_code": "agent_daemon_control_not_applicable",
            },
            "execution_run_control": {
                "supported": True,
                "scope": "run_id",
                "actions": ["observe", "cancel"],
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
