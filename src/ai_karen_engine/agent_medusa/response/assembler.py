"""Canonical Medusa response assembly (AGENT-LIVE-1 P0-5 / A13).

Replaces the canned `final_content = "Execution complete.""` returned by
MedusaCoordinator. Synthesizes actual agent step outputs into a final
assistant response through the existing ResponseContract / ResponseSynthesizer
path (already imported but unused in the coordinator).

Audited existing services before adding anything:
- services/response/response_contracts.ResponseContract  (purpose="medusa_synthesis")
- services/response/response_synthesizer.ResponseSynthesizer
- services/response/response_sanitizer.ResponseSanitizer
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..contracts.runtime_response import RuntimeResponse, ResponseStatus

logger = logging.getLogger(__name__)


class ResponseAssembler:
    """Synthesizes agent execution artifacts into a final response."""

    async def assemble(
        self,
        *,
        request_id: str,
        step_outputs: List[Dict[str, Any]],
        agent_trace: List[str],
        latest_user_message: str,
        status: ResponseStatus = ResponseStatus.SUCCESS,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RuntimeResponse:
        if not step_outputs:
            return RuntimeResponse(
                request_id=request_id,
                status=ResponseStatus.ERROR,
                content="No agent produced output for this request.",
                agent_trace=agent_trace,
                metadata=metadata or {},
            )

        from ai_karen_engine.services.response.response_contracts import ResponseContract
        from ai_karen_engine.services.response.response_synthesizer import ResponseSynthesizer
        from ai_karen_engine.services.models.routing.llm_router_service import get_llm_router

        contract = ResponseContract(
            purpose="medusa_synthesis",
            intent="agent.multi_agent",
            latest_user_message=latest_user_message,
            specialist_findings=step_outputs,
            runtime_metadata=metadata or {},
        )
        synthesizer = ResponseSynthesizer(get_llm_router())
        text, synth_metadata = await synthesizer.synthesize(
            contract, conversation_id=request_id
        )

        return RuntimeResponse(
            request_id=request_id,
            status=status,
            content=text,
            intermediate_steps=step_outputs,
            agent_trace=agent_trace,
            metadata={**(metadata or {}), "synthesis": synth_metadata},
        )
