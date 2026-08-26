"""
Diagnostics Module

Provides preflight simulation and analysis without side effects.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Any as AnyType

# from ai_karen_engine.services.llm_router import ChatRequest, LLMRouter  <- Moved to local scope
from ai_karen_engine.core.memory.signals.distilbert_service import DistilBertService, SafetyResult
from ai_karen_engine.core.memory.profile_synthesis.profile_manager import ProfileManager

from .contracts.orchestration_state import LangGraphOrchestrationState
from .decision_engine import DecisionEngine
from .nodes.planner import _compose_execution_plan

logger = logging.getLogger(__name__)


class DiagnosticsEngine:
    """Provides dry-run analysis and diagnostics"""

    def __init__(
        self,
        decision_engine: Optional[DecisionEngine] = None,
        llm_router: Optional[Any] = None,
        profile_manager: Optional[ProfileManager] = None,
    ):
        self._decision_engine = decision_engine or DecisionEngine()
        self._llm_router = llm_router
        self._profile_manager = profile_manager or ProfileManager()
        self._safety_service = DistilBertService()

    async def run_dry_run_analysis(
        self,
        *,
        message: str,
        session_id: Optional[str] = None,
        user: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Simulate orchestration without side effects for diagnostics.
        """
        user = user or {}
        context = context or {}

        session_identifier = (
            session_id or context.get("session_id") or f"dryrun-{uuid.uuid4()}"
        )
        user_id = user.get("id") or user.get("user_id") or "anonymous"
        tenant_id = (
            user.get("tenant_id")
            or user.get("organization_id")
            or context.get("tenant_id")
            or "default"
        )

        conversation_history = context.get("conversation_history")
        if not isinstance(conversation_history, list):
            conversation_history = []

        sanitized_history: List[Dict[str, Any]] = []
        for entry in conversation_history:
            if isinstance(entry, dict) and "content" in entry:
                sanitized_history.append(entry)

        user_settings = context.get("user_settings")
        if not isinstance(user_settings, dict):
            user_settings = {}

        memories = context.get("memories")
        if not isinstance(memories, list):
            memories = None

        built_context = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "session_id": session_identifier,
            "prompt": message,
            "conversation_history": sanitized_history,
            "user_settings": user_settings,
            "memories": memories or [],
        }

        intent_analysis = await self._decision_engine.analyze_intent(
            message, built_context
        )

        suggested_tools = intent_analysis.get("suggested_tools", []) or []
        entities = intent_analysis.get("entities", []) or []
        tool_calls: List[Dict[str, Any]] = []

        for tool_name in suggested_tools:
            parameters: Dict[str, Any] = {}
            for entity in entities:
                entity_type = (entity.get("type") or "").lower()
                value = entity.get("value")
                if not value:
                    continue
                if entity_type == "location":
                    parameters.setdefault("location", value)
                elif entity_type == "book":
                    parameters.setdefault("book_title", value)
                elif entity_type == "time":
                    parameters.setdefault("time_reference", value)

            tool_calls.append({"tool": tool_name, "parameters": parameters})

        safety_result: SafetyResult = await self._safety_service.filter_safety(message)
        if not safety_result.is_safe and safety_result.flagged_categories:
            safety_status = "review_required"
        elif safety_result.is_safe:
            safety_status = "safe"
        else:
            safety_status = "unsafe"

        execution_plan = _compose_execution_plan(
            intent_analysis.get("primary_intent", "conversation"),
            intent_analysis,
            tool_calls,
            safety_status,
        )

        provider_selection = None
        if self._llm_router:
            provider_preferences = {}
            for candidate in (
                context.get("llm_preferences"),
                context.get("user_preferences"),
                user.get("llm_preferences"),
                user_settings.get("llm_preferences")
                if isinstance(user_settings, dict)
                else None,
            ):
                if isinstance(candidate, dict):
                    provider_preferences.update(candidate)

            llm_request = ChatRequest(
                message=message,
                context={
                    "conversation": sanitized_history,
                    "plan": execution_plan,
                    "safety": {
                        "status": safety_status,
                        "score": safety_result.safety_score,
                        "flags": safety_result.flagged_categories,
                    },
                    "tenant_id": tenant_id,
                },
                tools=[call["tool"] for call in tool_calls] or None,
                memory_context=built_context.get("context_summary")
                if isinstance(built_context, dict)
                else None,
                user_preferences=provider_preferences or None,
                preferred_model=provider_preferences.get("chat")
                if isinstance(provider_preferences, dict)
                else None,
                conversation_id=session_identifier,
                stream=False,
            )

            provider_selection = await self._llm_router.select_provider(
                llm_request,
                user_preferences=provider_preferences,
            )

        if provider_selection:
            predicted_provider, predicted_model = provider_selection
            routing_reason = "Selected via LLM router policy"
            routing_confidence = 0.9
        else:
            predicted_provider, predicted_model = "fallback", "kari-fallback-v1"
            routing_reason = "Router returned no healthy provider; using fallback"
            routing_confidence = 0.2

        approval_required = bool(
            execution_plan.get("requires_human_review")
            or not safety_result.is_safe
            or execution_plan.get("complexity") == "high"
        )

        memories_considered = 0
        if isinstance(built_context, dict):
            memories_data = built_context.get("memories")
            if isinstance(memories_data, list):
                memories_considered = len(memories_data)

        analysis_timestamp = datetime.now(timezone.utc).isoformat()

        return {
            "session_id": session_identifier,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "message": message,
            "predicted_intent": intent_analysis.get("primary_intent", "conversation"),
            "intent_confidence": intent_analysis.get("confidence", 0.0),
            "routing_reason": routing_reason,
            "routing_confidence": routing_confidence,
            "predicted_provider": predicted_provider,
            "predicted_model": predicted_model,
            "estimated_processing_time": execution_plan.get(
                "estimated_time_seconds", 0.0
            ),
            "required_tools": [call["tool"] for call in tool_calls],
            "tool_parameters": tool_calls,
            "execution_plan": execution_plan,
            "safety_assessment": {
                "status": safety_status,
                "score": safety_result.safety_score,
                "flagged_categories": safety_result.flagged_categories,
                "used_fallback": safety_result.used_fallback,
            },
            "approval_required": approval_required,
            "context_summary": (
                built_context.get("context_summary")
                if isinstance(built_context, dict)
                else None
            ),
            "memories_considered": memories_considered,
            "timestamp": analysis_timestamp,
            "user_preferences": provider_preferences if provider_selection else {},
        }
