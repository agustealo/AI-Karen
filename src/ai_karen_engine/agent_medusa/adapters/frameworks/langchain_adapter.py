"""LangChain compatibility adapter for Agent Medusa.

LangChain is not an execution authority. This adapter preserves callers that
select the historical framework surface while delegating the authorized request
to the canonical MedusaCoordinator.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Optional

from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionTopology,
)
from ai_karen_engine.core.runtime.workflow_runtime import _serialize_plan

from ...contracts.runtime_request import RuntimeRequest
from ...contracts.runtime_response import RuntimeResponse
from ...coordinator.medusa_coordinator import MedusaCoordinator


class LangChainAdapter:
    """Compatibility surface that routes specialist work through Medusa."""

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
        agent_id: str,
        plan: Optional[AuthorizedExecutionPlan] = None,
    ) -> RuntimeResponse:
        """Delegate one authorized agent-constrained request to Medusa."""

        if plan is None:
            raise PermissionError(
                "LangChain specialist execution requires RuntimePolicy plan"
            )
        if plan.topology is not ExecutionTopology.MULTI_AGENT:
            raise PermissionError(
                "LangChain specialist execution requires multi-agent topology"
            )
        if not plan.matches_execution_scope(
            user_id=str(request.user_id or "").strip(),
            tenant_id=str(request.tenant_id or "").strip(),
            session_id=request.session_id,
            policy_decision_id=plan.policy_decision_id,
        ):
            raise PermissionError("LangChain RuntimePolicy execution scope mismatch")
        if "*" not in set(plan.allowed_agents) and agent_id not in set(plan.allowed_agents):
            raise PermissionError(
                "LangChain specialist is not authorized by RuntimePolicy"
            )
        if not request.execution_requirements:
            raise PermissionError(
                "LangChain specialist execution requires CORTEX requirements"
            )

        scoped_plan = replace(plan, allowed_agents=[agent_id])
        governed_request = replace(
            request,
            authorized_plan=_serialize_plan(scoped_plan),
        )
        coordinator = await self._get_coordinator()
        return await coordinator.handle_request(governed_request)
