"""
Medusa Adapter for Agent Integration Service.

This adapter bridges the legacy AgentIntegrationService to the canonical
AgentMedusa runtime, allowing multi-agent requests to be handled by
MedusaCoordinator instead of the legacy orchestration machinery.
"""

import logging
from typing import Any, AsyncGenerator, Dict, Optional

from ..models import (
    AgentRequest,
    AgentResponse,
    AgentStreamResponse,
    StreamChunk,
    AgentError,
)

logger = logging.getLogger(__name__)


class MedusaAdapter:
    """Adapter for delegating multi-agent execution to AgentMedusa."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._coordinator = None

    async def _get_coordinator(self):
        if self._coordinator is None:
            from ai_karen_engine.agent_medusa.coordinator.medusa_coordinator import (
                MedusaCoordinator,
            )
            self._coordinator = MedusaCoordinator()
        return self._coordinator

    async def execute(self, request: AgentRequest) -> AgentResponse:
        """Execute a multi-agent request via MedusaCoordinator."""
        coordinator = await self._get_coordinator()
        from ai_karen_engine.agent_medusa.contracts.runtime_request import (
            RuntimeRequest,
        )

        capabilities = [
            cap.value if hasattr(cap, "value") else str(cap)
            for cap in (request.capabilities_required or [])
        ]
        runtime_request = RuntimeRequest(
            query=request.message,
            session_id=request.session_id or "unknown",
            request_id=request.request_id,
            user_id=request.user_id,
            context={
                "legacy_agent_request": {
                    "agent_id": request.agent_id,
                    "execution_mode": (
                        request.execution_mode.value
                        if hasattr(request.execution_mode, "value")
                        else str(request.execution_mode)
                    ),
                    "capabilities": capabilities,
                    "config": request.config.custom_config if request.config else {},
                }
            },
        )

        try:
            response = await coordinator.handle_request(runtime_request)
            return AgentResponse(
                request_id=request.request_id,
                agent_id=request.agent_id or "medusa",
                execution_mode=request.execution_mode,
                response=response.content,
                processing_time=0.0,
                metadata=response.metadata or {},
            )
        except Exception as exc:
            logger.error(f"Medusa execution error: {exc}")
            return AgentResponse(
                request_id=request.request_id,
                agent_id=request.agent_id or "medusa",
                execution_mode=request.execution_mode,
                response="",
                processing_time=0.0,
                error=AgentError(
                    code="MEDUSA_EXECUTION_ERROR",
                    message=str(exc),
                    recoverable=True,
                    details={"exception_type": type(exc).__name__},
                ),
            )

    async def execute_stream(
        self, request: AgentRequest
    ) -> AsyncGenerator[AgentStreamResponse, None]:
        """Execute a multi-agent request with streaming via MedusaCoordinator."""
        response = await self.execute(request)
        yield AgentStreamResponse(
            request_id=request.request_id,
            agent_id=response.agent_id,
            execution_mode=response.execution_mode,
            chunk=StreamChunk(
                content=response.response,
                chunk_type="text",
                is_final=True,
            ),
            is_complete=True,
            metadata=response.metadata,
        )
