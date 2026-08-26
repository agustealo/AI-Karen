"""Response synthesis node for LangGraph orchestration."""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ai_karen_engine.services.response import ResponseSanitizer
from ai_karen_engine.core.runtime.provider_runtime import ProviderRuntime
from ai_karen_engine.core.model_runtime.runtime_contracts import ProviderExecutionResult
from ai_karen_engine.core.runtime.prompt import get_prompt_runtime_service
from ..contracts.orchestration_state import LangGraphOrchestrationState
from ..utils.message_serialization import message_to_history_entry

logger = logging.getLogger(__name__)


@dataclass
class SynthesisConfig:
    """Configuration for response synthesis."""
    max_response_length: int = 100000
    include_tool_results: bool = True
    include_execution_summary: bool = True
    apply_safety_filter: bool = True


class ResponseSynthesisNode:
    """Deterministic response synthesis over orchestration state."""

    def __init__(
        self, 
        config: Optional[SynthesisConfig] = None, 
        llm_router: Optional[Any] = None,
        provider_runtime: Optional[ProviderRuntime] = None
    ):
        self.config = config or SynthesisConfig()
        self._llm_router = llm_router
        self._provider_runtime = provider_runtime or ProviderRuntime(llm_router)
        self._response_sanitizer = ResponseSanitizer()

    async def __call__(
        self, state: LangGraphOrchestrationState
    ) -> LangGraphOrchestrationState:
        logger.info("Response synthesis processing")
        try:
            response = await self._compose_response(state)
            state["llm_response"] = response
            state["response"] = response  # Ensure both are set for compatibility
            
            exec_result = state.get("execution_result")
            if exec_result:
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
                "included_tool_results": len(state.get("tool_results") or [])
                if self.config.include_tool_results
                else 0,
                "included_execution_summary": bool(
                    state.get("execution_summary") and self.config.include_execution_summary
                ),
                "included_reasoning_summary": bool(state.get("reasoning_result")),
            }
            if self.config.apply_safety_filter:
                state = self._apply_safety_filter(state)
            logger.info("Response synthesis completed")
        except Exception as e:
            logger.error("Response synthesis error: %s", e)
            state.setdefault("errors", []).append(f"Response synthesis error: {e}")
        return state

    async def _compose_response(self, state: LangGraphOrchestrationState) -> str:
        messages = state.get("messages") or []
        last_user_message = self._extract_last_user_message(messages)
        tool_results = state.get("tool_results") or []
        reasoning_result = state.get("reasoning_result") or {}
        request_config = state.get("request_config") or {}
        request_preferences = dict(request_config) if isinstance(request_config, dict) else {}
        
        route_decision = state.get("route_decision")

        if route_decision and self._provider_runtime:
            try:
                # Local import to avoid circular dependency
                from ai_karen_engine.core.model_runtime.routing.llm_router_service import ChatRequest

                cortex = state.get("cortex")
                intent = "general.chat"
                subtype = None
                
                if cortex and hasattr(cortex, "intent"):
                    intent = cortex.intent.primary_intent
                    subtype = getattr(cortex.intent, "subtype", None)
                elif isinstance(cortex, dict):
                    intent_data = cortex.get("intent", {})
                    if isinstance(intent_data, dict):
                        intent = intent_data.get("primary_intent", "general.chat")
                        subtype = intent_data.get("subtype")

                prompt_runtime = get_prompt_runtime_service()
                prompt_request = prompt_runtime.build_request_from_runtime_context(
                    messages=[message_to_history_entry(message) for message in messages],
                    request_context=request_config,
                    integrated_context=state.get("memory_context") or {},
                    profile=state.get("user_profile") or {},
                    workflow_context={
                        "plan": state.get("execution_plan"),
                        "tool_results": tool_results,
                        "reasoning_result": reasoning_result,
                    },
                    cortex_intent={
                        "primary_intent": intent,
                        "subtype": subtype,
                    },
                    token_budget=int(
                        request_preferences.get("token_budget")
                        or request_preferences.get("max_input_tokens")
                        or 4096
                    ),
                )
                assembled_prompt = await prompt_runtime.assemble_prompt(prompt_request)

                request = ChatRequest(
                    message=last_user_message or "",
                    intent=intent,
                    subtype=subtype,
                    context={
                        "messages": assembled_prompt.messages,
                        "prompt_text": prompt_runtime.render_text_prompt(assembled_prompt.messages),
                        "prompt_hash": assembled_prompt.prompt_hash,
                        "prompt_metadata": assembled_prompt.metadata,
                        "truncation_events": [
                            {
                                "section": event.section,
                                "reason": event.reason,
                                "items_removed": event.items_removed,
                            }
                            for event in assembled_prompt.truncation_events
                        ],
                    },
                    preferred_model=route_decision.selected_model,
                    stream=False,
                    conversation_id=state.get("session_id"),
                )

                exec_result = await self._provider_runtime.execute_chat(
                    route_decision,
                    request,
                    user_preferences=request_preferences
                )
                
                state["execution_result"] = exec_result
                
                if exec_result.text.strip():
                    llm_metadata = self._build_metadata_from_result(exec_result, bool(state.get("streaming_enabled")))
                    self._store_llm_metadata(state, llm_metadata)
                    logger.info(
                        "LLM synthesis successful. Actual provider: %s",
                        exec_result.actual_provider,
                    )
                    return exec_result.text.strip()

            except Exception as e:
                logger.warning(f"LLM-based synthesis via ProviderRuntime failed: {e}")

        # Deterministic fallback if LLM synthesis fails or was skipped
        fallback = self._compose_deterministic_fallback(
            last_user_message=last_user_message,
            tool_results=tool_results,
            execution_summary=state.get("execution_summary") or {},
            reasoning_result=reasoning_result,
        )

        response = self._response_sanitizer.sanitize(fallback)
        if len(response) > self.config.max_response_length:
            response = response[: self.config.max_response_length].rstrip() + "... (truncated)"
        
        # Build emergency metadata if we reached this point
        exec_result = state.get("execution_result")
        if not exec_result or exec_result.response_source == "emergency_static":
            emergency_metadata = {
                "requested_provider": request_preferences.get("preferred_llm_provider") or "unknown",
                "requested_model": request_preferences.get("preferred_model") or "unknown",
                "selected_provider": None,
                "selected_model": None,
                "actual_provider": None,
                "actual_model": None,
                "runtime_engine": "none",
                "response_source": "emergency_static",
                "fallback_level": 99,
                "degraded_mode": True,
                "degradation_type": "fallback_exhausted",
                "degradation_reason": "No active cloud providers are configured. Built-in runtimes may still be available in Model Settings.",
                "provider_attempts": exec_result.provider_attempts if exec_result else [],
                "latency_ms": exec_result.latency_ms if exec_result else 0,
                "streaming_enabled": bool(state.get("streaming_enabled")),
            }
            self._store_llm_metadata(state, emergency_metadata)

        return response

    def _build_metadata_from_result(self, result: ProviderExecutionResult, streaming_enabled: bool) -> Dict[str, Any]:
        """Build forensic metadata from ProviderExecutionResult."""
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
        last_user_message: Optional[str],
        tool_results: List[Dict[str, Any]],
        execution_summary: Dict[str, Any],
        reasoning_result: Dict[str, Any],
    ) -> str:
        if tool_results and self.config.include_tool_results:
            return self._format_tool_results(tool_results)
        if isinstance(reasoning_result, dict) and reasoning_result.get("summary"):
            return str(reasoning_result["summary"]).strip()
        if execution_summary and self.config.include_execution_summary:
            successful = execution_summary.get("successful_executions", 0)
            failed = execution_summary.get("failed_executions", 0)
            return f"I completed the request with {successful} successful step(s) and {failed} failed step(s)."
        return "I’m here and ready to help, but I’m currently operating with limited capacity. Please try again in a moment."

    @staticmethod
    def _store_llm_metadata(
        state: LangGraphOrchestrationState, llm_metadata: Dict[str, Any]
    ) -> None:
        state["llm_metadata"] = llm_metadata
        
        # Pull memory context telemetry if available
        memory_context = state.get("memory_context") or {}
        memory_metadata = {}
        if memory_context:
            context_meta = memory_context.get("context_metadata") or {}
            memory_metadata = {
                "used": bool(memory_context.get("memories")),
                "classes": memory_context.get("memory_types_found") or [],
                "recall_mode": "curated" if context_meta.get("curated_recall") else "semantic",
                "sources": ["vector_db", "postgres"] if memory_context.get("memories") else [],
                "latency_ms": context_meta.get("latency_ms"),
                "degraded": bool(memory_context.get("error") or state.get("memory_fetch_error")),
                "writeback_status": "completed" if state.get("memory_writeback_completed") else "pending"
            }

        response_metadata = {
            **(state.get("response_metadata") or {}),
            "llm": {
                **llm_metadata,
                "memory": memory_metadata
            },
            "memory": memory_metadata,
            "degraded_mode": bool(llm_metadata.get("degraded_mode")),
            "response_source": llm_metadata.get("response_source"),
            "actual_provider": llm_metadata.get("actual_provider"),
            "actual_model": llm_metadata.get("actual_model"),
        }
        state["response_metadata"] = response_metadata
        state["degraded_mode"] = bool(llm_metadata.get("degraded_mode"))

    def _extract_last_user_message(self, messages: List[Any]) -> Optional[str]:
        for message in reversed(messages):
            role = getattr(message, "type", None) or getattr(message, "role", None)
            content = getattr(message, "content", None)
            if role in {"human", "user"} and content:
                return str(content).strip()
        return None

    def _format_tool_results(self, tool_results: List[Dict[str, Any]]) -> str:
        rendered_results: List[str] = []
        for result in tool_results[:5]:
            tool_name = result.get("tool_name") or result.get("tool") or "tool"
            if result.get("success", result.get("status") == "success"):
                output = result.get("output")
                rendered_results.append(f"{tool_name}: {output}")
            else:
                rendered_results.append(
                    f"{tool_name}: failed ({result.get('error') or 'unknown error'})"
                )
        if not rendered_results:
            return ""
        return "Tool results: " + "; ".join(rendered_results)

    def _apply_safety_filter(
        self, state: LangGraphOrchestrationState
    ) -> LangGraphOrchestrationState:
        response = state.get("llm_response", "")
        if not isinstance(response, str):
            return state

        safety_flags = state.get("safety_flags") or []
        if safety_flags and len(response) > 0:
            state["llm_response"] = response.replace("unsafe", "[filtered]")
        return state


async def response_synth_node(
    state: LangGraphOrchestrationState,
    llm_router: Optional[Any] = None,
) -> LangGraphOrchestrationState:
    """Convenience wrapper for LangGraph orchestration."""
    node = ResponseSynthesisNode(llm_router=llm_router)
    return await node(state)

