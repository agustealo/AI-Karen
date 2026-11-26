"""Medusa response assembly through the existing governed generation bridge.

A completed single Deep Agents answer retains its original provenance.
Other successful specialist outputs are data for final synthesis, never
a source of model authorization or provider selection.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ..contracts.specialist_execution import SpecialistExecutionContext

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
        execution: Optional["SpecialistExecutionContext"] = None,
    ) -> RuntimeResponse:
        # Plan-level specialist degradation is independent of the model
        # receipt for final synthesis. A later healthy model cannot erase it.
        upstream = metadata or {}
        specialist_degraded = upstream.get("degraded_mode") is True
        if specialist_degraded and status is ResponseStatus.SUCCESS:
            status = ResponseStatus.DEGRADED

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
                    "model_calls_observed": output.get("model_calls_observed"),
                    "actual_provider": output.get("actual_provider"),
                    "actual_model": output.get("actual_model"),
                    "model_selection_source": output.get("model_selection_source"),
                    "learning_signal_status": output.get("learning_signal_status"),
                    "learning_signal_version": output.get("learning_signal_version"),
                    "learned_context_status": output.get("learned_context_status"),
                    "learned_memory_refs_included": output.get(
                        "learned_memory_refs_included", 0
                    ),
                    "runtime_engine": output.get("runtime_engine"),
                    "synthesis": {"source": "agent_harness", "additional_model_calls": 0},
                },
            )

        if status not in {ResponseStatus.SUCCESS, ResponseStatus.PARTIAL,
                          ResponseStatus.DEGRADED}:
            return RuntimeResponse(
                request_id=request_id, status=status,
                content="The agent run did not complete successfully.",
                intermediate_steps=step_outputs, agent_trace=agent_trace,
                metadata=metadata or {},
            )

        from ai_karen_engine.core.runtime.contracts import GenerationRequest
        from ai_karen_engine.services.response.response_contracts import ResponseContract
        from ai_karen_engine.services.response.response_prompt_builder import ResponsePromptBuilder
        from ai_karen_engine.services.response.response_sanitizer import ResponseSanitizer
        from ai_karen_engine.services.response.response_validator import ResponseValidator
        from ..specialists.bridges import CanonicalGenerationExecutor

        if execution is None or execution.trajectory_id != request_id:
            raise PermissionError("medusa_final_synthesis_authority_required")
        contract = ResponseContract(
            purpose="medusa_synthesis",
            intent="agent.multi_agent",
            latest_user_message=latest_user_message,
            specialist_findings=step_outputs,
        )
        result = await CanonicalGenerationExecutor().generate_result(
            GenerationRequest(
                request_id=request_id,
                correlation_id=execution.correlation_id,
                policy_decision_id=execution.policy_decision_id,
                messages=ResponsePromptBuilder().build_messages(contract),
            ),
            execution=execution,
        )
        text = ResponseSanitizer().sanitize(result.text)
        if not ResponseValidator().validate(text, contract).valid:
            raise RuntimeError("medusa_final_synthesis_validation_failed")

        if result.degraded and status is ResponseStatus.SUCCESS:
            status = ResponseStatus.DEGRADED
        receipt = {
            "response_source": result.response_source,
            "actual_provider": result.provider,
            "actual_model": result.model,
            "runtime_engine": result.runtime_engine,
            "fallback_level": result.metadata.get("fallback_level", 0),
            "degraded_mode": result.degraded,
            "degradation_reason": result.degradation_reason,
            "latency_ms": result.latency_ms,
            "correlation_id": execution.correlation_id,
        }
        return RuntimeResponse(
            request_id=request_id,
            status=status,
            content=text,
            intermediate_steps=step_outputs,
            agent_trace=agent_trace,
            metadata={
                **upstream,
                **receipt,
                "degraded_mode": (
                    specialist_degraded
                    or result.degraded
                    or status is ResponseStatus.DEGRADED
                ),
                "degradation_reason": (
                    result.degradation_reason or upstream.get("degradation_reason")
                ),
                **(
                    {
                        "specialist_degradation": {
                            "degraded_mode": True,
                            "degradation_reason": upstream.get("degradation_reason"),
                            "fallback_level": upstream.get("fallback_level"),
                            "affected_agents": upstream.get("affected_agents", []),
                        }
                    }
                    if specialist_degraded
                    else {}
                ),
                "synthesis": {"source": "expression_gateway", **receipt},
            },
        )
