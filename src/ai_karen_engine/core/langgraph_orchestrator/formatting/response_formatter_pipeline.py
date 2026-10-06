"""
Response Formatter Pipeline

Centralized response formatting and envelope generation for all API responses.
Ensures consistent output formatting and policy enforcement.
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime, timezone

from ..contracts.orchestration_state import LangGraphOrchestrationState
from ai_karen_engine.utils.chat_helpers import (
    strip_internal_analysis_leakage,
    finalize_user_visible_text,
)
from ai_karen_engine.services.formatting.response_formatting_engine import (
    ResponseFormattingEngine,
    FormattingContext,
    DisplayContext,
    AccessibilityLevel,
)
from ai_karen_engine.services.formatting.response_policy_enforcer import ResponsePolicyEnforcer
from ai_karen_engine.services.formatting.pretty_output_layer import (
    PrettyOutputLayer,
)

try:
    from ai_karen_engine.services.formatting.ResponseFormattingClass.Specialized.Integration import (
        get_specialized_integration,
    )
except ImportError:
    get_specialized_integration = None

logger = logging.getLogger(__name__)


@dataclass
class ResponseEnvelope:
    """Standardized response envelope for all API responses"""

    status: str = "success"
    data: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    errors: Optional[List[str]] = None
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class ResponsePolicyEnforcer:
    """Enforces response formatting policies and constraints"""

    def __init__(self):
        self.restricted_fields = {
            "internal_state",
            "raw_llm_response",
            "intermediate_steps",
            "debug_info",
            "system_metrics",
        }

    def enforce_policies(self, response_data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply response formatting policies"""
        cleaned_response = {}

        # Copy allowed fields
        for key, value in response_data.items():
            if key not in self.restricted_fields:
                cleaned_response[key] = value

        # Ensure required fields
        if "response" not in cleaned_response:
            cleaned_response["response"] = cleaned_response.get("content", "")

        # Enforce data limits
        if isinstance(cleaned_response.get("response"), str):
            if len(cleaned_response["response"]) > 100000:  # 100k char limit
                cleaned_response["response"] = (
                    cleaned_response["response"][:100000] + "... (truncated)"
                )

        return cleaned_response


class ResponseFormatterPipeline:
    """Unified response formatting pipeline for all API responses"""

    def __init__(self):
        self.formatting_engine = ResponseFormattingEngine()
        self.policy_enforcer = ResponsePolicyEnforcer()
        self.pretty_layer = PrettyOutputLayer()

    async def format_response_with_engine(
        self,
        response_text: str,
        state: LangGraphOrchestrationState,
    ) -> tuple[str, Dict[str, Any]]:
        """Run the full formatting and policy enforcement pipeline"""
        # 1. Initial cleanup
        user_message = state.get("message", "")
        cleaned_text = finalize_user_visible_text(response_text, user_message)

        # 2. Build context
        formatting_ctx = self._build_formatting_context(state)

        # 3. Apply primary formatting
        formatted_result = await self.formatting_engine.format_response(
            cleaned_text, formatting_ctx
        )

        # 4. Apply policy enforcement
        policy_result = await self.policy_enforcer.enforce_policies(
            formatted_result.formatted_text,
            intent=state.get("detected_intent", "unknown"),
        )

        # 5. Apply pretty output layer
        final_text = await self.pretty_layer.render(
            policy_result.content,
            metadata={
                "intent": state.get("detected_intent"),
                "sentiment": state.get("intent_analysis", {}).get("sentiment"),
            },
        )
        
        # Final pass after all rendering to ensure structure is still clean
        final_text = finalize_user_visible_text(final_text, user_message)

        # 6. Extract specialized payload (for UI components)
        formatting_payload = {}
        if get_specialized_integration is not None:
            specialized_integration = get_specialized_integration()
            formatting_payload = await specialized_integration.extract_payload(
                final_text,
                context={
                    "intent": state.get("detected_intent"),
                    "tool_results": state.get("tool_results"),
                },
            )

        return final_text, formatting_payload

    def _build_formatting_context(
        self, state: LangGraphOrchestrationState
    ) -> FormattingContext:
        """Build formatting context from state"""
        return FormattingContext(
            display_context=DisplayContext.CONVERSATION,
            accessibility_level=AccessibilityLevel.STANDARD,
            user_preferences=state.get("user_profile", {}).get("preferences", {}),
            conversation_context=state.get("conversation_history", []),
        )

    async def format_response(
        self,
        state: LangGraphOrchestrationState,
        raw_response: Optional[Dict[str, Any]] = None,
    ) -> ResponseEnvelope:
        """
        Format response through unified pipeline

        Flow: response_synth node → response_policy_enforcer → response_formatter_pipeline → response_envelope
        """
        logger.info("Formatting response through unified pipeline")

        try:
            # Start with raw response or extract from state
            if raw_response is None:
                raw_response = self._extract_raw_response(state)

            # Apply policy enforcement
            formatted_data = self.policy_enforcer.enforce_policies(raw_response)

            # Add metadata
            metadata = self._generate_metadata(state, formatted_data)

            # Create envelope
            envelope = ResponseEnvelope(
                data=formatted_data, metadata=metadata, errors=state.get("errors")
            )

            logger.info("Response formatting completed successfully")
            return envelope

        except Exception as e:
            logger.error(f"Response formatting error: {e}")
            return ResponseEnvelope(
                status="error", errors=[f"Response formatting error: {str(e)}"]
            )

    def build_response_envelope(
        self,
        final_text: str,
        provider: str,
        model: str,
        metadata: Optional[Dict[str, Any]] = None,
        suggestions: Optional[List[str]] = None,
        alerts: Optional[List[Dict[str, Any]]] = None,
        status: str = "ok",
    ) -> Dict[str, Any]:
        """Build a standard envelope using the LangGraph-owned formatter path."""
        meta = dict(metadata or {})
        meta.setdefault("provider", provider)
        meta.setdefault("model", model)
        meta.setdefault("timestamp", datetime.now(timezone.utc).isoformat())

        return {
            "final": finalize_user_visible_text(final_text, ""),
            "status": status,
            "meta": meta,
            "suggestions": list(suggestions or []),
            "alerts": list(alerts or []),
        }

    def _extract_raw_response(
        self, state: LangGraphOrchestrationState
    ) -> Dict[str, Any]:
        """Extract raw response from orchestration state"""
        response_data = {}

        # Extract different response components
        if "llm_response" in state:
            response_data["response"] = state["llm_response"]

        if "tool_results" in state:
            response_data["tool_results"] = state["tool_results"]

        if "execution_summary" in state:
            response_data["execution_summary"] = state["execution_summary"]

        if "selected_provider" in state:
            response_data["provider"] = state["selected_provider"]

        if "selected_model" in state:
            response_data["model"] = state["selected_model"]

        if "execution_plan" in state:
            response_data["execution_plan"] = state["execution_plan"]

        # Preserve only declared user-facing rich result fields. The response
        # policy enforcer still strips internal state before Runtime sees it.
        for key in (
            "structured_content",
            "actions",
            "citations",
            "sources",
            "attachments",
            "artifacts",
        ):
            value = state.get(key)
            if value is not None:
                response_data[key] = value

        # Add conversation context
        if "messages" in state:
            response_data["conversation_context"] = state["messages"][
                -5:
            ]  # Last 5 messages

        return response_data

    def _generate_metadata(
        self, state: LangGraphOrchestrationState, response_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate response metadata"""
        existing_metadata = dict(state.get("response_metadata") or {})
        llm_metadata = dict(
            existing_metadata.get("llm") or state.get("llm_metadata") or {}
        )
        metadata = {
            "session_id": state.get("session_id"),
            "request_id": state.get("request_id"),
            "processing_time_ms": state.get("processing_time_ms"),
            "safety_status": state.get("safety_status", "unknown"),
            "routing_decision": state.get("routing_reason"),
            "streaming_enabled": state.get("streaming_enabled", False),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        metadata.update(existing_metadata)
        if llm_metadata:
            metadata["llm"] = llm_metadata
            metadata.setdefault("requested_provider", llm_metadata.get("requested_provider"))
            metadata.setdefault("requested_model", llm_metadata.get("requested_model"))
            metadata.setdefault("actual_provider", llm_metadata.get("actual_provider"))
            metadata.setdefault("actual_model", llm_metadata.get("actual_model"))
            metadata.setdefault("runtime_engine", llm_metadata.get("runtime_engine"))
            metadata.setdefault("response_source", llm_metadata.get("response_source"))
            metadata.setdefault("provider_health", llm_metadata.get("provider_health", {}))
            metadata.setdefault("provider_error", llm_metadata.get("provider_error"))
            metadata.setdefault("fallback_level", llm_metadata.get("fallback_level", 0))
            metadata.setdefault("degraded_mode", llm_metadata.get("degraded_mode", False))
            metadata.setdefault("degradation_reason", llm_metadata.get("degradation_reason"))

        # Add execution metrics if available
        if "execution_metrics" in state:
            metadata["execution_metrics"] = state["execution_metrics"]

        return metadata


async def response_formatter_node(
    state: LangGraphOrchestrationState,
) -> LangGraphOrchestrationState:
    """
    Response formatting node for LangGraph orchestration

    Ensures all responses pass through unified formatter
    """
    logger.info("Response formatting processing")

    try:
        # Initialize pipeline
        pipeline = ResponseFormatterPipeline()

        # Format response
        envelope = await pipeline.format_response(state)

        # Update state with formatted response
        state["formatted_response"] = envelope
        state["response_status"] = envelope.status
        if envelope.metadata:
            state["response_metadata"] = {
                **(state.get("response_metadata") or {}),
                **envelope.metadata,
            }

        if envelope.errors:
            state.setdefault("errors", []).extend(envelope.errors)

        logger.info("Response formatting completed")

    except Exception as e:
        logger.error(f"Response formatting error: {e}")
        state.setdefault("errors", []).append(f"Response formatting error: {str(e)}")

    return state
