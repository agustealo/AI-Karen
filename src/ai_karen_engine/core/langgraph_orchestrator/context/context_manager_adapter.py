from __future__ import annotations

from typing import Optional, Any, Dict, List
import logging
from datetime import datetime, timezone

from ai_karen_engine.core.runtime.session_state_port import SessionStatePort
from ..utils.message_serialization import (
    message_to_history_entry,
    history_entry_to_message,
)

logger = logging.getLogger(__name__)



async def ensure_session_state_manager(
    orchestrator_instance: Any,
) -> Optional[SessionStatePort]:
    """Return the session-state implementation injected at composition time.

    Core deliberately does not discover CopilotKit or any other outer session
    implementation. A caller that wants durable graph continuity must inject a
    SessionStatePort when constructing the orchestrator.
    """
    manager = getattr(orchestrator_instance, "_session_state_manager", None)
    if manager is None:
        if not getattr(orchestrator_instance, "_session_state_resolution_failed", False):
            logger.debug("No SessionStatePort was injected; graph continuity is disabled")
        orchestrator_instance._session_state_resolution_failed = True
        return None
    if not isinstance(manager, SessionStatePort):
        logger.warning("Injected session-state object does not satisfy SessionStatePort")
        orchestrator_instance._session_state_resolution_failed = True
        return None
    return manager


async def build_runtime_context(
    orchestrator_instance: Any,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    context: Dict[str, Any] = {}
    context_sources: Dict[str, Any] = {}

    if "messages" in state:
        conversation_history = [message_to_history_entry(msg) for msg in state["messages"]]
        context["conversation_history"] = conversation_history
        context_sources["runtime_context"] = {
            "source": "runtime_context",
            "messages": len(conversation_history),
        }

    if "user_profile" in state:
        context["user_profile"] = state["user_profile"]
        context["user_settings"] = state["user_profile"].get("preferences", {})
        context_sources["user_profile"] = {"source": "runtime_context", "present": True}

    if "memory_context" in state:
        context["memory_context"] = state["memory_context"]
        context_sources["memory_context"] = {
            "source": "memory_context",
            "present": state["memory_context"] is not None,
        }

    if "saved_contexts" in state:
        context["saved_contexts"] = state["saved_contexts"]
        context_sources["saved_contexts"] = {
            "source": "saved_context",
            "present": bool(state["saved_contexts"]),
        }

    if "file_context" in state:
        context["file_context"] = state["file_context"]
        context_sources["file_context"] = {
            "source": "file_context",
            "present": state["file_context"] is not None,
        }

    if context_sources:
        context["context_sources"] = context_sources
    return context


async def load_session_continuity(
    orchestrator_instance: Any,
    session_id: str,
) -> Optional[Dict[str, Any]]:
    session_manager = await ensure_session_state_manager(orchestrator_instance)
    if not session_manager or not session_id:
        return None
    try:
        loaded = await session_manager.load_session_state(session_id)
        return dict(loaded) if loaded is not None else None
    except Exception as exc:
        logger.warning("Failed to load session state for %s: %s", session_id, exc)
        return None


async def save_session_continuity(
    orchestrator_instance: Any,
    session_id: str,
    response: str,
    messages: List[Any],
) -> None:
    session_manager = await ensure_session_state_manager(orchestrator_instance)
    if not session_manager or not session_id:
        return
    try:
        recent_turns = []
        for msg in messages[-6:]:
            role = "user" if msg.__class__.__name__ == "HumanMessage" else "assistant"
            recent_turns.append({"role": role, "content": msg.content[:120]})
        session_state = {
            "last_user_message": messages[-2].content[:280] if len(messages) >= 2 else "",
            "last_assistant_response": response[:280],
            "recent_turns": recent_turns,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await session_manager.save_session_state(session_id, session_state)
    except Exception as exc:
        logger.warning("Failed to save session state for %s: %s", session_id, exc)


def serialize_messages(messages: List[Any]) -> List[Dict[str, Any]]:
    return [message_to_history_entry(msg) for msg in messages]


def deserialize_messages(serialized: List[Dict[str, Any]]) -> List[Any]:
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

    messages = []
    for entry in serialized:
        role = entry.get("role")
        content = entry.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
        elif role == "system":
            messages.append(SystemMessage(content=content))
    return messages


def extract_last_user_content(messages: List[Any]) -> Optional[str]:
    for msg in reversed(messages):
        if msg.__class__.__name__ == "HumanMessage":
            return msg.content
    return None
