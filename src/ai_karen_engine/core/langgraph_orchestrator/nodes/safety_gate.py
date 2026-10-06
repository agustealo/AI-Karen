import logging
from dataclasses import asdict
from typing import Optional

from ai_karen_engine.core.memory.signals.distilbert_service import DistilBertService, SafetyResult
from ai_karen_engine.core.memory.profile_synthesis.profile_manager import (
    ProfileManager,
    Guardrails,
)
from ..contracts.orchestration_state import LangGraphOrchestrationState

logger = logging.getLogger(__name__)


class SafetyGateNode:
    """Safety and guardrails gate"""

    def __init__(self, profile_manager=None):
        self._profile_manager = profile_manager or ProfileManager()
        self._safety_service: Optional[DistilBertService] = None

    def _ensure_safety_service(self) -> DistilBertService:
        """Lazy instantiate safety service."""
        if self._safety_service is None:
            self._safety_service = DistilBertService()
        return self._safety_service

    async def __call__(
        self, state: LangGraphOrchestrationState
    ) -> LangGraphOrchestrationState:
        """Process safety checks"""
        logger.info("Safety gate processing")

        try:
            errors = state.setdefault("errors", [])
            warnings = state.setdefault("warnings", [])
            messages = state.get("messages", [])

            if not messages:
                state["safety_status"] = "safe"
                state["safety_evaluation"] = {"reason": "no_messages"}
                return state

            last_message = (
                messages[-1].content
                if hasattr(messages[-1], "content")
                else str(messages[-1])
            )

            profile = self._profile_manager.get_active_profile()
            guardrails: Optional[Guardrails] = getattr(profile, "guardrails", None)

            if guardrails and not guardrails.content_filtering:
                state["safety_status"] = "safe"
                state["safety_evaluation"] = {"reason": "guardrails_disabled"}
                return state

            safety_service = self._ensure_safety_service()
            evaluation: SafetyResult = await safety_service.filter_safety(last_message)
            state["safety_evaluation"] = asdict(evaluation)

            if not evaluation.is_safe and evaluation.flagged_categories:
                state["safety_status"] = "review_required"
                state["safety_flags"] = evaluation.flagged_categories
                warnings.append(
                    "Safety service flagged content for review: "
                    + ", ".join(evaluation.flagged_categories)
                )
                state["degraded_mode"] = True
                state.setdefault("degradation_reasons", []).append("safety_flag")
            elif evaluation.is_safe:
                state["safety_status"] = "safe"
                state["safety_flags"] = []
            else:
                state["safety_status"] = "unsafe"
                errors.append("Content failed safety evaluation")

        except Exception as e:
            logger.error(f"Safety gate error: {e}")
            state["safety_status"] = "unsafe"
            state.setdefault("errors", []).append(f"Safety check error: {str(e)}")
            state["degraded_mode"] = True
            state.setdefault("degradation_reasons", []).append("safety_error")

        return state


async def safety_gate_node(
    state: LangGraphOrchestrationState,
    profile_manager=None,
) -> LangGraphOrchestrationState:
    """Convenience wrapper for SafetyGateNode"""
    node = SafetyGateNode(profile_manager)
    return await node(state)
