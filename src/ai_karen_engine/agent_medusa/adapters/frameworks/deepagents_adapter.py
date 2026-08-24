"""
DeepAgents adapter for AgentMedusa.

Routes multi-agent execution through MedusaCoordinator, preserving
the AuthorizedExecutionPlan and using Medusa's specialist registry
and bridges for model/tool access.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ...contracts.runtime_request import RuntimeRequest
from ...contracts.runtime_response import RuntimeResponse, ResponseStatus
from ...coordinator.medusa_coordinator import MedusaCoordinator

logger = logging.getLogger(__name__)


class DeepAgentsAdapter:
    """DeepAgents execution adapter for Medusa.

    Provides multi-agent execution by delegating to MedusaCoordinator,
    which resolves specialists from the registry and executes them
    according to the AuthorizedExecutionPlan.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._coordinator: Optional[MedusaCoordinator] = None

    async def _get_coordinator(self) -> MedusaCoordinator:
        if self._coordinator is None:
            self._coordinator = MedusaCoordinator()
        return self._coordinator

    async def execute(
        self,
        request: RuntimeRequest,
        plan: Optional[AuthorizedExecutionPlan] = None,
    ) -> RuntimeResponse:
        coordinator = await self._get_coordinator()
        if plan is not None:
            request.authorized_plan = {
                "execution_id": plan.execution_id,
                "policy_decision_id": plan.policy_decision_id,
                "topology": plan.topology.value if hasattr(plan.topology, "value") else str(plan.topology),
                "allowed_capabilities": list(plan.allowed_capabilities),
                "allowed_tools": list(plan.allowed_tools),
                "allowed_plugins": list(plan.allowed_plugins),
                "allowed_agents": list(plan.allowed_agents),
                "provider_constraints": dict(plan.provider_constraints),
                "memory_scope": plan.memory_scope,
                "resource_scope": dict(plan.resource_scope),
                "budget": plan.budget.__dict__ if hasattr(plan.budget, "__dict__") else {},
                "approval_requirements": list(plan.approval_requirements),
                "reasoning_modes": list(plan.reasoning_modes),
                "workflow_id": plan.workflow_id,
                "agent_topology": plan.agent_topology,
                "degraded_allowed": plan.degraded_allowed,
                "degradation_state": plan.degradation_state.__dict__ if plan.degradation_state else None,
                "audit_context": dict(plan.audit_context),
            }
        return await coordinator.handle_request(request)
