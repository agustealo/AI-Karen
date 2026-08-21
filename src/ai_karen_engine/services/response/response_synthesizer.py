from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

from ai_karen_engine.services.provider_runtime import ProviderRuntime
from ai_karen_engine.core.model_runtime.runtime_contracts import ProviderExecutionResult, ProviderRouteDecision
from .response_contracts import ResponseContract
from .response_prompt_builder import ResponsePromptBuilder
from .response_sanitizer import ResponseSanitizer
from .response_validator import ResponseValidator

logger = logging.getLogger(__name__)

class ResponseSynthesizer:
    def __init__(self, llm_router: Any):
        self.llm_router = llm_router
        self.provider_runtime = ProviderRuntime(llm_router)
        self.prompt_builder = ResponsePromptBuilder()
        self.sanitizer = ResponseSanitizer()
        self.validator = ResponseValidator()

    async def synthesize(self, contract: ResponseContract, *, user_preferences: dict[str, Any] | None = None, conversation_id: str | None = None, stream: bool = False) -> tuple[str, dict[str, Any]]:
        from ai_karen_engine.services.models.routing.llm_router_service import ChatRequest
        
        prefs = user_preferences or {}
        
        # Determine intent and subtype if not already set
        if contract.intent == "general.chat" and not contract.subtype:
            try:
                from ai_karen_engine.core.cortex.routing_intents import resolve_capability_decision
                decision = resolve_capability_decision(contract.latest_user_message)
                contract.intent = decision.intent
                contract.subtype = decision.subtype
            except ImportError:
                pass

        request = ChatRequest(
            message=contract.latest_user_message,
            intent=contract.intent,
            subtype=contract.subtype,
            response_mode=contract.response_mode,
            context={
                "messages": self.prompt_builder.build_messages(contract),
                "response_contract": {"purpose": contract.purpose, "intent": contract.intent, "subtype": contract.subtype},
                "tool_results": contract.tool_results,
                "specialist_findings": contract.specialist_findings,
                "reasoning_summary": contract.reasoning_summary,
                "runtime_metadata": contract.runtime_metadata,
            },
            stream=stream,
            preferred_provider=prefs.get("preferred_llm_provider") or prefs.get("provider"),
            preferred_model=prefs.get("preferred_model") or prefs.get("model"),
            conversation_id=conversation_id,
        )

        # 1. Route
        route_decision = await self.llm_router.select_provider(request, user_preferences=prefs)
        
        # 2. Execute
        if route_decision:
            exec_result = await self.provider_runtime.execute_chat(route_decision, request, user_preferences=prefs)
            text = exec_result.text
            metadata = self._build_metadata_from_result(exec_result)
        else:
            logger.warning("No route decision available for synthesis; returning emergency static truth.")
            exec_result = self.provider_runtime._build_emergency_result(  # noqa: SLF001
                decision=ProviderRouteDecision(
                    requested_provider=prefs.get("preferred_llm_provider") or prefs.get("provider"),
                    requested_model=prefs.get("preferred_model") or prefs.get("model"),
                    selected_provider=None,
                    selected_model=None,
                    provider_category=None,
                    compatibility_profile=None,
                    runtime_engine=None,
                    transport=None,
                    selection_source="no_route",
                    fallback_level=99,
                    degraded_mode=True,
                    degradation_type="fallback_exhausted",
                    degradation_reason="No active cloud providers are configured. Built-in runtimes may still be available in Model Settings.",
                    provider_healthy=False,
                    model_available=False,
                    allowed_for_current_user=False,
                    correlation_id=conversation_id or "",
                ),
                request=request,
                correlation_id=conversation_id or "",
                start_time=time.time(),
                provider_attempts=[{
                    "provider": None,
                    "model": None,
                    "status": "failed",
                    "error_type": "provider_missing",
                    "error_message": "No provider decision was available.",
                    "latency_ms": 0.0,
                }],
                degraded_message="I'm having trouble connecting to my brain right now. Please try again.",
            )
            text = exec_result.text
            metadata = self._build_metadata_from_result(exec_result)
        
        # Validation and potential retry
        validation = self.validator.validate(text, contract)
        if not validation.valid and text:
            logger.warning(f"Response validation failed: {validation.reason}. Attempting retry with stricter contract.")
            
            # Stricter contract for retry
            contract.disallow_unrequested_menu = True
            contract.disallow_debug_prefixes = True
            
            retry_request = ChatRequest(
                message=contract.latest_user_message,
                intent=contract.intent,
                subtype=contract.subtype,
                response_mode=contract.response_mode,
                context={
                    "messages": self.prompt_builder.build_messages(contract),
                    "retry_attempt": 1,
                    "previous_error": validation.reason,
                },
                stream=stream,
                conversation_id=conversation_id,
            )
            
            # Re-route for retry might choose a different model if needed, but we'll stick to same for now or let router decide
            retry_decision = await self.llm_router.select_provider(retry_request, user_preferences=prefs)
            if retry_decision:
                retry_result = await self.provider_runtime.execute_chat(retry_decision, retry_request, user_preferences=prefs)
                text = retry_result.text
                metadata = self._build_metadata_from_result(retry_result)
            
            # Final validation check
            final_validation = self.validator.validate(text, contract)
            if not final_validation.valid:
                logger.error(f"Response validation failed again after retry: {final_validation.reason}")
                if contract.purpose == "chat" and not text:
                     text = "I'm sorry, I'm having trouble generating a valid response right now. Please try again or switch models."

        return self.sanitizer.sanitize(text), metadata

    def _build_metadata_from_result(self, result: ProviderExecutionResult) -> Dict[str, Any]:
        """Build legacy-compatible metadata from ProviderExecutionResult."""
        return {
            "requested_provider": result.requested_provider,
            "requested_model": result.requested_model,
            "selected_provider": result.selected_provider,
            "selected_model": result.selected_model,
            "actual_provider": result.actual_provider,
            "actual_model": result.actual_model,
            "provider": result.actual_provider,
            "model_id": result.actual_model,
            "runtime_engine": result.runtime_engine,
            "response_source": result.response_source,
            "fallback_level": result.fallback_level,
            "degraded_mode": result.degraded_mode,
            "latency_ms": result.latency_ms,
            "correlation_id": result.correlation_id,
        }
