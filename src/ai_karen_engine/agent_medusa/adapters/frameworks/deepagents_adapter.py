"""
DeepAgents adapter for AgentMedusa.

Routes multi-agent execution through MedusaCoordinator, preserving
the AuthorizedExecutionPlan and using Medusa's specialist registry
and bridges for model/tool access.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.core.runtime.workflow_runtime import _serialize_plan
from ...contracts.runtime_request import RuntimeRequest
from ...contracts.runtime_response import RuntimeResponse
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
            request.authorized_plan = _serialize_plan(plan)
        return await coordinator.handle_request(request)

