from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ContextManager:
    """Thin LangGraph compatibility adapter for conversational memory context.

    Runtime/PromptRuntime own final context assembly. File upload state is owned
    separately by FileContextStore. This adapter only enriches an already-scoped
    conversational request with canonical memory-service context.
    """

    def __init__(self, memory_service: Optional[Any] = None):
        self.memory_service = memory_service

    async def build_context(
        self,
        *,
        user_id: str,
        tenant_id: Optional[str],
        session_id: Optional[str],
        prompt: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        user_settings: Optional[Dict[str, Any]] = None,
        memories: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        context: Dict[str, Any] = {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "session_id": session_id,
            "prompt": prompt,
            "conversation_history": conversation_history or [],
            "user_settings": user_settings or {},
            "memories": memories or [],
        }

        memory_service = self.memory_service
        if memory_service is not None and tenant_id and hasattr(memory_service, "build_context"):
            try:
                retrieved_context = await memory_service.build_context(
                    tenant_id=tenant_id,
                    query=prompt,
                    user_id=user_id,
                    session_id=session_id,
                    conversation_id=session_id,
                )
                if isinstance(retrieved_context, dict):
                    context.update(retrieved_context)
            except TypeError:
                logger.debug(
                    "Memory service build_context signature mismatch; using LangGraph compatibility context"
                )
            except Exception as exc:
                logger.warning("LangGraph context memory enrichment failed: %s", exc)
        elif memory_service is not None and not tenant_id:
            logger.warning("LangGraph memory enrichment skipped: missing tenant_id")

        return context

    def clear_context_cache(self) -> None:
        """Compatibility no-op until remaining callers stop requesting cache clears."""

        return None


__all__ = ["ContextManager"]
