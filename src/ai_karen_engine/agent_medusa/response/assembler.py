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

        # Deep Agents has already synthesized a complete answer. If and only
        # if this is the sole verified specialist contribution, preserve it
        # without another provider call. Multi-specialist evidence still uses
        # the canonical synthesizer below.
        if len(step_outputs) == 1 and step_outputs[0].get("harness") == "deepagents":
            output = step_outputs[0]
            content = output.get("context_found")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Deep Agents completed without valid response content")
            if status not in {ResponseStatus.SUCCESS, ResponseStatus.PARTIAL,
                              ResponseStatus.DEGRADED}:
                return RuntimeResponse(
                    request_id=request_id,
                    status=status,
                    content="The agent run did not complete successfully.",
                    intermediate_steps=step_outputs,
                    agent_trace=agent_trace,
                    metadata=metadata or {},
                )
            return RuntimeResponse(
                request_id=request_id,
                status=status,
                content=content,
                intermediate_steps=step_outputs,
                agent_trace=agent_trace,
                metadata={
                    **(metadata or {}),
                    "response_source": "deepagents_verified_output",
                    "synthesis": {"source": "agent_harness", "additional_model_calls": 0},
                },
            )

        from ai_karen_engine.services.response.response_contracts import ResponseContract
        from ai_karen_engine.services.response.response_synthesizer import ResponseSynthesizer
        from ai_karen_engine.core.model_runtime.routing.llm_router_service import get_llm_router

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

