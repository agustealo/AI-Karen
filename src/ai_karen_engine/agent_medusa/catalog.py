"""Agent catalog / capability descriptors (AGENT-LIVE-1 A19 / A20).

Exposes a backend-driven agent surface for the UI:

    registered
    ∩ tenant-visible
    ∩ RBAC-visible
    ∩ policy-eligible

Normal users see usable agents. Admins see disabled/unauthorized agents
with diagnostic status (why each filter excluded them).

Tenant/RBAC/policy sets are injected from upstream authority (RuntimePolicy,
RBAC) — this module does NOT own authorization; it only intersects the sets
it is given. capability_health feeds the DEGRADED vs AVAILABLE distinction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .contracts.registration import AgentRegistration, AgentLifecycleState
from .registry import MedusaRegistry

logger = logging.getLogger(__name__)


@dataclass
class AgentDescriptor:
    """Backend-confirmed descriptor for one agent, as exposed to the UI."""

    agent_id: str
    name: str
    description: str
    version: str
    lifecycle_state: str
    status: str
    capabilities: List[str] = field(default_factory=list)
    implementation_id: Optional[str] = None
    prompt_contract_id: Optional[str] = None
    prompt_version: Optional[str] = None
    healthy: bool = True
    missing_dependencies: List[str] = field(default_factory=list)
    diagnostic: Dict[str, Any] = field(default_factory=dict)


class AgentCatalogService:
    """Builds filtered, backend-driven agent descriptors from the registry."""

    def __init__(self, registry: MedusaRegistry) -> None:
        self.registry = registry

    async def list_agents(
        self,
        *,
        tenant_visible_ids: Optional[Set[str]] = None,
        rbac_visible_ids: Optional[Set[str]] = None,
        policy_eligible_ids: Optional[Set[str]] = None,
        include_disabled: bool = False,
        capability_health: Optional[Any] = None,
        admin: bool = False,
    ) -> List[AgentDescriptor]:
        agents = await self.registry.list_agents()
        out: List[AgentDescriptor] = []
        for reg in agents:
            health = await self.registry.get_agent_health(reg.agent_id, capability_health)
            diagnostic = {
                "tenant_visible": tenant_visible_ids is None or reg.agent_id in tenant_visible_ids,
                "rbac_visible": rbac_visible_ids is None or reg.agent_id in rbac_visible_ids,
                "policy_eligible": policy_eligible_ids is None or reg.agent_id in policy_eligible_ids,
                "healthy": health.get("healthy", True),
            }

            if not admin:
                # Normal users only see agents that pass every filter and are active.
                if (
                    reg.lifecycle_state
                    in (AgentLifecycleState.DISABLED, AgentLifecycleState.ARCHIVED)
                    and not include_disabled
                ):
                    continue
                if not (
                    diagnostic["tenant_visible"]
                    and diagnostic["rbac_visible"]
                    and diagnostic["policy_eligible"]
                ):
                    continue

            out.append(self._to_descriptor(reg, health, diagnostic))
        return out

    def _to_descriptor(self, reg: AgentRegistration, health: Dict[str, Any], diagnostic: Dict[str, Any]) -> AgentDescriptor:
        return AgentDescriptor(
            agent_id=reg.agent_id,
            name=reg.name,
            description=reg.name and reg.description,
            version=reg.version,
            lifecycle_state=reg.lifecycle_state,
            status=reg.status,
            capabilities=[c.type.value for c in reg.capabilities],
            implementation_id=reg.implementation_id,
            prompt_contract_id=reg.prompt_contract_id,
            prompt_version=reg.prompt_version,
            healthy=health.get("healthy", True),
            missing_dependencies=health.get("missing_dependencies", []),
            diagnostic=diagnostic,
        )
