import logging
from typing import List, Dict, Any
from ..contracts.orchestration_state import LangGraphOrchestrationState
from ..context.context_manager_adapter import (
    ensure_context_manager,
    ensure_session_state_manager,
    save_session_continuity,
)
from ..utils.message_serialization import message_to_history_entry
from ai_karen_engine.utils.chat_helpers import (
    build_structured_context_sections,
    wants_long_form_markdown_article,
)
from ai_karen_engine.core.memory.profile_synthesis import get_profile_service

logger = logging.getLogger(__name__)


class MemoryFetchNode:
    """Memory and context fetching with Profile Synthesis and salvaged session state retrieval."""

    def __init__(self):
        self.profile_service = get_profile_service()

    async def __call__(
        self, state: LangGraphOrchestrationState
    ) -> LangGraphOrchestrationState:
        """Memory and context fetching with Profile Synthesis and salvaged session state retrieval."""
        logger.info("Memory fetch processing (Profile-Synthesis-Aware)")

        try:
            errors = state.setdefault("errors", [])
            warnings = state.setdefault("warnings", [])
            messages = state.get("messages", [])
            user_id = state.get("user_id")
            tenant_id = state.get("tenant_id")
            if not tenant_id:
                warnings.append("Memory disabled for this turn: missing tenant_id")

            conversation_history = [
                message_to_history_entry(message) for message in messages
            ]
            state["conversation_history"] = conversation_history

            if user_id:
                try:
                    profile_summary = await self.profile_service.get_profile_summary(
                        user_id,
                        tenant_id,
                    )
                    state["user_profile_summary"] = profile_summary.dict()
                    legacy_profile = state.get("user_profile") or {}
                    legacy_profile.update(
                        {
                            "id": str(profile_summary.user_id),
                            "preferences": profile_summary.top_preferences,
                            "style": profile_summary.communication_style.dict(),
                            "roles": profile_summary.roles,
                        }
                    )
                    state["user_profile"] = legacy_profile
                    logger.debug(
                        "Synthesized profile for %s with %s facts.",
                        user_id,
                        profile_summary.stable_facts_count,
                    )
                except Exception as prof_err:
                    logger.warning("Profile synthesis failed for %s: %s", user_id, prof_err)

            if not messages:
                state["memory_context"] = {
                    "conversation_history": [],
                    "context_summary": "No prior context",
                    "memories": [],
                }
                return state

            context_manager = await ensure_context_manager(self)
            user_profile = state.get("user_profile") or {}
            user_settings = user_profile.get("preferences", {})
            prompt = conversation_history[-1]["content"]

            import time

            memory_start = time.time()
            context = await context_manager.build_context(
                user_id=user_id,
                tenant_id=tenant_id,
                session_id=state.get("session_id"),
                prompt=prompt,
                conversation_history=conversation_history,
                user_settings=user_settings,
                memories=None,
            )
            memory_latency = (time.time() - memory_start) * 1000

            state["memory_context"] = context
            if isinstance(context, dict):
                context.setdefault("context_metadata", {})["latency_ms"] = memory_latency

            session_state_manager = await ensure_session_state_manager(self)
            session_id = state.get("session_id")
            if session_state_manager and session_id:
                from ..context.context_manager_adapter import load_session_continuity

                session_state = await load_session_continuity(self, session_id)
                if session_state:
                    state["memory_context"]["session_state"] = session_state
                    warnings.append(
                        f"Retrieved salvaged session state for {session_id}"
                    )

            if isinstance(context, dict):
                structured_sections = build_structured_context_sections(
                    request_context=state.get("request_config", {}),
                    integrated_context=context,
                )
                state["memory_context"]["structured_sections"] = structured_sections

                if conversation_history:
                    is_long_form = wants_long_form_markdown_article(
                        current_user_message=conversation_history[-1]["content"],
                        recent_messages=conversation_history,
                    )
                    state["memory_context"]["is_long_form_requested"] = is_long_form

            if isinstance(context, dict) and context.get("memories"):
                state.setdefault("warnings", []).append(
                    f"Loaded {len(context['memories'])} contextual memories"
                )

        except Exception as e:
            logger.error("Memory fetch error: %s", e)
            errors = state.setdefault("errors", [])
            errors.append(f"Memory fetch error: {str(e)}")

        return state


async def memory_fetch_node(
    state: LangGraphOrchestrationState,
) -> LangGraphOrchestrationState:
    """Convenience wrapper for MemoryFetchNode"""
    node = MemoryFetchNode()
    return await node(state)
