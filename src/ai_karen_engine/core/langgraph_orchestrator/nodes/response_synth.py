"""Response synthesis node for authorized LangGraph workflows.

The graph owns workflow-local synthesis context. Runtime owns prompt assembly,
provider/model routing, provider execution, fallback semantics, and actual
provider/model provenance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.model_runtime.runtime_contracts import ProviderExecutionResult
from ai_karen_engine.core.runtime.workflow_generation import (
    WorkflowGenerationRequest,
    WorkflowGenerationRuntime,
    get_workflow_generation_runtime,
)
from ai_karen_engine.services.response import ResponseSanitizer

from ..contracts.orchestration_state import LangGraphOrchestrationState
from ..utils.message_serialization import message_to_history_entry

logger = logging.getLogger(__name__)


@dataclass
class SynthesisConfig:
    max_response_length: int = 100000
    include_tool_results: bool = True
    include_execution_summary: bool = True
    apply_safety_filter: bool = True


class ResponseSynthesisNode:
    """Assemble workflow context and delegate model generation to Runtime."""

    def __init__(
        self,
        config: Optional[SynthesisConfig] = None,
        *,
        workflow_generation_runtime: Optional[WorkflowGenerationRuntime] = None,
        llm_router: Any = None,
    ) -> None:
        self.config = config or SynthesisConfig()
        self._workflow_generation_runtime = (
            workflow_generation_runtime or get_workflow_generation_runtime()
        )
        self._compat_llm_router = llm_router
        self._response_sanitizer = ResponseSanitizer()

    async def __call__(
        self,
        state: LangGraphOrchestrationState,
    ) -> LangGraphOrchestrationState:
        logger.info("Response synthesis processing")
        try:
            response = await self._compose_response(state)
            state["llm_response"] = response
            state["response"] = response

            exec_result = state.get("execution_result")
            if isinstance(exec_result, ProviderExecutionResult):
                state["synthesis_metadata"] = {
                    "response_length": len(response),
                    "tool_results_count": len(state.get("tool_results") or []),
                    "selected_provider": exec_result.selected_provider,
                    "selected_model": exec_result.selected_model,
                    "actual_provider": exec_result.actual_provider,
                    "actual_model": exec_result.actual_model,
                    "provider_category": exec_result.provider_category,
                    "latency_ms": exec_result.latency_ms,
                    "has_reasoning_result": bool(state.get("reasoning_result")),
                    "provider_attempts": exec_result.provider_attempts,
                }

            state["response_summary"] = {
                "response_length": len(response),
                "included_tool_results": (
                    len(state.get("tool_results") or [])
                    if self.config.include_tool_results
                    else 0
                ),
                "included_execution_summary": bool(
                    state.get("execution_summary")
                    and self.config.include_execution_summary
                ),
                "included_reasoning_summary": bool(state.get("reasoning_result")),
            }
            if self.config.apply_safety_filter:
                state = self._apply_safety_filter(state)
            logger.info("Response synthesis completed")
        except Exception as exc:
            logger.error("Response synthesis error: %s", exc)
            state.setdefault("errors", []).append(f"Response synthesis error: {exc}")
        return state

    async def _compose_response(self, state: LangGraphOrchestrationState) -> str:
        messages = state.get("messages") or []
        tool_results = state.get("tool_results") or []
        reasoning_result = state.get("reasoning_result") or {}
        request_config = state.get("request_config") or {}
        request_context = dict(request_config) if isinstance(request_config, dict) else {}
        runtime_policy = state.get("runtime_policy")

        if not isinstance(runtime_policy, dict):
            raise PermissionError(
                "Response synthesis requires AuthorizedExecutionPlan from RuntimePolicy"
            )

        profile = state.get("user_profile") or {}
        profile_dict = dict(profile) if isinstance(profile, dict) else {}
        generation_request = WorkflowGenerationRequest(
            request_id=str(state.get("request_id") or ""),
            correlation_id=str(state.get("correlation_id") or ""),
            tenant_id=str(state.get("tenant_id") or ""),
            user_id=str(state.get("user_id") or ""),
            conversation_id=(
                str(state.get("conversation_id"))
                if state.get("conversation_id")
                else state.get("session_id")
            ),
            policy_decision_id=str(runtime_policy.get("policy_decision_id") or ""),
            messages=[message_to_history_entry(message) for message in messages],
            request_context=request_context,
            integrated_context=dict(state.get("memory_context") or {}),
            profile=profile_dict,
            workflow_context={
                "plan": state.get("execution_plan"),
                "tool_results": tool_results,
                "reasoning_result": reasoning_result,
                "safety_evaluation": state.get("safety_evaluation"),
            },
            cortex_intent=self._cortex_intent(state, request_context),
            authorized_plan=dict(runtime_policy),
            stream=False,
        )

        exec_result = await self._workflow_generation_runtime.execute(generation_request)
        state["execution_result"] = exec_result
        state["route_decision"] = None
        state["selected_provider"] = exec_result.selected_provider
        state["selected_model"] = exec_result.selected_model
        state["routing_reason"] = "Provider/model resolved by Runtime workflow generation"

        llm_metadata = self._build_metadata_from_result(
            exec_result,
            bool(state.get("streaming_enabled")),
        )
        self._store_llm_metadata(state, llm_metadata)

        if exec_result.text.strip():
            logger.info(
                "Workflow generation completed via Runtime actual_provider=%s",
                exec_result.actual_provider,
            )
            return self._truncate(exec_result.text.strip())

        fallback = self._compose_deterministic_fallback(
            tool_results=tool_results,
            execution_summary=state.get("execution_summary") or {},
            reasoning_result=reasoning_result,
        )
        return self._truncate(self._response_sanitizer.sanitize(fallback))

    @staticmethod
    def _cortex_intent(
        state: LangGraphOrchestrationState,
        request_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        primary = (
            request_context.get("intent")
            or request_context.get("primary_intent")
            or state.get("detected_intent")
            or "general.chat"
        )
        return {
            "primary_intent": str(primary),
            "subtype": request_context.get("intent_subtype"),
        }

    def _truncate(self, response: str) -> str:
        if len(response) <= self.config.max_response_length:
            return response
        return response[: self.config.max_response_length].rstrip() + "... (truncated)"

    @staticmethod
    def _build_metadata_from_result(
        result: ProviderExecutionResult,
        streaming_enabled: bool,
    ) -> Dict[str, Any]:
        return {
            "requested_provider": result.requested_provider,
            "requested_model": result.requested_model,
            "selected_provider": result.selected_provider,
            "selected_model": result.selected_model,
            "actual_provider": result.actual_provider,
            "actual_model": result.actual_model,
            "provider": result.actual_provider,
            "model_id": result.actual_model,
            "model_name": result.actual_model,
            "provider_category": result.provider_category,
            "runtime_engine": result.runtime_engine,
            "transport": result.transport,
            "response_source": result.response_source,
            "source": result.response_source,
            "fallback_level": result.fallback_level,
            "degraded_mode": result.degraded_mode,
            "is_degraded": result.degraded_mode,
            "used_fallback": result.fallback_level > 0,
            "degradation_type": result.degradation_type,
            "degradation_reason": result.degradation_reason,
            "latency_ms": result.latency_ms,
            "duration": result.latency_ms / 1000 if result.latency_ms else 0,
            "streaming_enabled": streaming_enabled,
            "correlation_id": result.correlation_id,
            "provider_attempts": result.provider_attempts,
            "usage": result.usage,
            "tokens_per_second": result.metadata.get("tokens_per_second"),
            "finish_reason": result.finish_reason,
            "raw_metadata": result.metadata,
        }

    def _compose_deterministic_fallback(
        self,
        *,
        tool_results: List[Dict[str, Any]],
        execution_summary: Dict[str, Any],
        reasoning_result: Dict[str, Any],
    ) -> str:
        if tool_results and self.config.include_tool_results:
            return self._format_tool_results(tool_results)
        if isinstance(reasoning_result, dict):
            conclusion = reasoning_result.get("conclusion") or reasoning_result.get(
                "summary"
            )
            if conclusion:
                return str(conclusion).strip()
        if execution_summary and self.config.include_execution_summary:
            successful = execution_summary.get("successful_executions", 0)
            failed = execution_summary.get("failed_executions", 0)
            return (
                f"Workflow completed with {successful} successful step(s) "
                f"and {failed} failed step(s), but no authorized model response "
                "was produced."
            )
        return (
            "No authorized model provider completed this workflow, so no model "
            "response was produced."
        )

    @staticmethod
    def _store_llm_metadata(
        state: LangGraphOrchestrationState,
        llm_metadata: Dict[str, Any],
    ) -> None:
        state["llm_metadata"] = llm_metadata
        memory_context = state.get("memory_context") or {}
        memory_metadata: Dict[str, Any] = {}
        if isinstance(memory_context, dict) and memory_context:
            context_meta = memory_context.get("context_metadata") or {}
            memory_metadata = {
                "used": bool(memory_context.get("memories")),
                "classes": memory_context.get("memory_types_found") or [],
                "recall_mode": (
                    "curated" if context_meta.get("curated_recall") else "semantic"
                ),
                "latency_ms": context_meta.get("latency_ms"),
                "degraded": bool(
                    memory_context.get("error") or state.get("memory_fetch_error")
                ),
            }

        state["response_metadata"] = {
            **(state.get("response_metadata") or {}),
            "llm": {**llm_metadata, "memory": memory_metadata},
            "memory": memory_metadata,
            "degraded_mode": bool(llm_metadata.get("degraded_mode")),
            "response_source": llm_metadata.get("response_source"),
            "actual_provider": llm_metadata.get("actual_provider"),
            "actual_model": llm_metadata.get("actual_model"),
        }
        state["degraded_mode"] = bool(llm_metadata.get("degraded_mode"))

    def _format_tool_results(self, tool_results: List[Dict[str, Any]]) -> str:
        rendered_results: List[str] = []
        for result in tool_results[:5]:
            tool_name = result.get("tool_name") or result.get("tool") or "tool"
            if result.get("success", result.get("status") == "success"):
                rendered_results.append(f"{tool_name}: {result.get('output')}")
            else:
                rendered_results.append(
                    f"{tool_name}: failed ({result.get('error') or 'unknown error'})"
                )
        return "Tool results: " + "; ".join(rendered_results)

    def _apply_safety_filter(
        self,
        state: LangGraphOrchestrationState,
    ) -> LangGraphOrchestrationState:
        response = state.get("llm_response", "")
        if isinstance(response, str) and state.get("safety_flags") and response:
            state["llm_response"] = response.replace("unsafe", "[filtered]")
            state["response"] = state["llm_response"]
        return state


async def response_synth_node(
    state: LangGraphOrchestrationState,
    llm_router: Any = None,
    workflow_generation_runtime: Optional[WorkflowGenerationRuntime] = None,
) -> LangGraphOrchestrationState:
    node = ResponseSynthesisNode(
        workflow_generation_runtime=workflow_generation_runtime,
        llm_router=llm_router,
    )
    return await node(state)
