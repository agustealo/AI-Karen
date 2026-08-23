import logging
from typing import Dict, Any, Optional
from dataclasses import asdict

# from ai_karen_engine.services.llm_router import ChatRequest  <- Moved to local scope
from ai_karen_engine.core.memory.profile_synthesis.profile_manager import ProfileManager
from ..contracts.orchestration_state import LangGraphOrchestrationState
from ..utils.message_serialization import message_to_history_entry

logger = logging.getLogger(__name__)


class RouterSelectNode:
    """LLM provider and model selection"""

    def __init__(self, llm_router=None, profile_manager=None):
        self._llm_router = llm_router
        self._profile_manager = profile_manager or ProfileManager()

    async def __call__(
        self, state: LangGraphOrchestrationState
    ) -> LangGraphOrchestrationState:
        """LLM provider and model selection"""
        logger.info("Router selection processing")

        try:
            # Local import to avoid circular dependency
            from ai_karen_engine.core.model_runtime.routing.llm_router_service import ChatRequest

            messages = state.get("messages", [])
            if not messages:
                state["selected_provider"] = "fallback"
                state["selected_model"] = "kari-fallback-v1"
                state["routing_reason"] = "No conversation context available"
                return state

            conversation_history = state.get("conversation_history") or [
                message_to_history_entry(message) for message in messages
            ]
            memory_context = state.get("memory_context") or {}
            plan = state.get("execution_plan", {})
            tool_calls = state.get("tool_calls") or []

            profile = self._profile_manager.get_active_profile()
            provider_preferences = (
                asdict(profile.provider_preferences)
                if profile and getattr(profile, "provider_preferences", None)
                else {}
            )
            request_config = state.get("request_config") or {}
            if isinstance(request_config, dict):
                # Check both common variants from different API ingress paths
                preferred_provider = request_config.get("provider") or request_config.get("preferred_llm_provider")
                preferred_model = request_config.get("model") or request_config.get("preferred_model")
                
                if preferred_provider and not provider_preferences.get(
                    "preferred_llm_provider"
                ):
                    provider_preferences["preferred_llm_provider"] = preferred_provider
                if preferred_model and not provider_preferences.get("preferred_model"):
                    provider_preferences["preferred_model"] = preferred_model
            
            explicit_preferred_provider = (
                request_config.get("provider") or request_config.get("preferred_llm_provider")
                if isinstance(request_config, dict)
                else None
            )
            explicit_preferred_model = (
                request_config.get("model") or request_config.get("preferred_model")
                if isinstance(request_config, dict)
                else None
            )
            preferred_model_name: Optional[str] = None
            if explicit_preferred_model:
                preferred_model_name = str(explicit_preferred_model)
            elif not explicit_preferred_provider:
                profile_chat_preference = provider_preferences.get("chat")
                if profile_chat_preference:
                    preferred_model_name = str(profile_chat_preference)

            cortex = state.get("cortex")
            intent = "general.chat"
            subtype = None
            requires_chat_capable_model = True
            
            if cortex and hasattr(cortex, "intent"):
                intent = cortex.intent.primary_intent
                subtype = getattr(cortex.intent, "subtype", None)
                requires_chat_capable_model = getattr(cortex.intent, "requires_chat_capable_model", True)
            elif isinstance(cortex, dict):
                intent_data = cortex.get("intent", {})
                if isinstance(intent_data, dict):
                    intent = intent_data.get("primary_intent", "general.chat")
                    subtype = intent_data.get("subtype")
                    requires_chat_capable_model = intent_data.get("requires_chat_capable_model", True)

            request = ChatRequest(
                message=conversation_history[-1]["content"],
                intent=intent,
                subtype=subtype,
                context={
                    "conversation": conversation_history,
                    "plan": plan,
                    "safety": state.get("safety_evaluation"),
                },
                tools=[call["tool"] for call in tool_calls],
                memory_context=memory_context.get("context_summary"),
                user_preferences=provider_preferences,
                preferred_model=preferred_model_name,
                conversation_id=state.get("session_id"),
                stream=bool(state.get("streaming_enabled")),
                requires_chat_capable_model=requires_chat_capable_model,
            )

            if self._llm_router:
                route_decision = await self._llm_router.select_provider(
                    request,
                    user_preferences=provider_preferences,
                )

                if route_decision:
                    state["route_decision"] = route_decision
                    state["selected_provider"] = route_decision.selected_provider
                    state["selected_model"] = route_decision.selected_model
                    state["routing_reason"] = route_decision.routing_reason or "Selected via LLM router policy"
                else:
                    state["route_decision"] = None
                    state["selected_provider"] = "fallback"
                    state["selected_model"] = "kari-fallback-v1"
                    state["routing_reason"] = (
                        "Router returned no provider; using fallback"
                    )
            else:
                state["route_decision"] = None
                state["selected_provider"] = "fallback"
                state["selected_model"] = "kari-fallback-v1"
                state["routing_reason"] = "LLM router not available; using fallback"

        except Exception as e:
            logger.error(f"Router selection error: {e}")
            state.setdefault("errors", []).append(f"Router selection error: {str(e)}")

        return state


async def router_select_node(
    state: LangGraphOrchestrationState,
    llm_router=None,
    profile_manager=None,
) -> LangGraphOrchestrationState:
    """Convenience wrapper for RouterSelectNode"""
    node = RouterSelectNode(llm_router, profile_manager)
    return await node(state)

