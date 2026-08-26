from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Dict, Optional

from ai_karen_engine.core.memory.profile_synthesis import get_profile_service
from ai_karen_engine.utils.chat_helpers import wants_long_form_markdown_article

from ..context.context_manager_adapter import (
    ensure_session_state_manager,
    load_session_continuity,
)
from ..contracts.orchestration_state import LangGraphOrchestrationState
from ..utils.message_serialization import message_to_history_entry

logger = logging.getLogger(__name__)

MemoryRecall = Callable[..., Awaitable[dict[str, Any]]]


class MemoryFetchNode:
    """Fetch tenant-scoped memory/profile context without owning prompt assembly."""

    def __init__(
        self,
        *,
        memory_recall: Optional[MemoryRecall] = None,
        memory_recall_top_k: int = 10,
        session_state_manager: Optional[Any] = None,
    ) -> None:
        self.profile_service = get_profile_service()
        self._memory_recall = memory_recall
        self._memory_recall_top_k = memory_recall_top_k
        self._session_state_manager = session_state_manager
        self._session_state_resolution_failed = False

    async def __call__(
        self, state: LangGraphOrchestrationState
    ) -> LangGraphOrchestrationState:
        logger.info("Memory fetch processing (Profile-Synthesis-Aware)")

        try:
            warnings = state.setdefault("warnings", [])
            messages = state.get("messages", [])
            user_id = state.get("user_id")
            tenant_id = state.get("tenant_id")

            conversation_history = [
                message_to_history_entry(message) for message in messages
            ]
            state["conversation_history"] = conversation_history

            if not tenant_id:
                warnings.append("Memory disabled for this turn: missing tenant_id")

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

            user_profile = state.get("user_profile") or {}
            user_settings = user_profile.get("preferences", {})
            prompt = conversation_history[-1]["content"]
            context: Dict[str, Any] = {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "session_id": state.get("session_id"),
                "prompt": prompt,
                "conversation_history": conversation_history,
                "user_settings": user_settings,
                "memories": [],
            }

            memory_start = time.time()
            if tenant_id and self._memory_recall is not None:
                try:
                    recalled = await self._memory_recall(
                        tenant_id=str(tenant_id),
                        user_id=user_id,
                        query=prompt,
                        session_id=state.get("session_id"),
                        conversation_id=state.get("session_id"),
                        top_k=self._memory_recall_top_k,
                    )
                    if isinstance(recalled, dict):
                        results = recalled.get("results", [])
                        if isinstance(results, list):
                            context["memories"] = results
                        context.setdefault("context_metadata", {}).update(
                            {
                                "memory_status": recalled.get("status"),
                                "memory_count": len(context["memories"]),
                                "memory_source": recalled.get("source", "memory_runtime"),
                            }
                        )
                        if recalled.get("status") == "degraded":
                            warnings.append("Memory recall unavailable for this turn")
                except Exception as memory_err:
                    logger.warning("Tenant-scoped memory recall failed: %s", memory_err)
                    warnings.append("Memory recall unavailable for this turn")

            memory_latency = (time.time() - memory_start) * 1000
            context.setdefault("context_metadata", {})["latency_ms"] = memory_latency
            state["memory_context"] = context

            session_state_manager = await ensure_session_state_manager(self)
            session_id = state.get("session_id")
            if session_state_manager and session_id:
                session_state = await load_session_continuity(self, session_id)
                if session_state:
                    state["memory_context"]["session_state"] = session_state
                    warnings.append(
                        f"Retrieved salvaged session state for {session_id}"
                    )

            is_long_form = wants_long_form_markdown_article(
                current_user_message=conversation_history[-1]["content"],
                recent_messages=conversation_history,
            )
            state["memory_context"]["is_long_form_requested"] = is_long_form

            if context.get("memories"):
                warnings.append(
                    f"Loaded {len(context['memories'])} contextual memories"
                )

        except Exception as exc:
            logger.error("Memory fetch error: %s", exc)
            state.setdefault("errors", []).append(f"Memory fetch error: {exc}")

        return state


async def memory_fetch_node(
    state: LangGraphOrchestrationState,
    *,
    memory_recall: Optional[MemoryRecall] = None,
    memory_recall_top_k: int = 10,
    session_state_manager: Optional[Any] = None,
) -> LangGraphOrchestrationState:
    """Execute memory fetch with composition-root supplied dependencies."""

    node = MemoryFetchNode(
        memory_recall=memory_recall,
        memory_recall_top_k=memory_recall_top_k,
        session_state_manager=session_state_manager,
    )
    return await node(state)
