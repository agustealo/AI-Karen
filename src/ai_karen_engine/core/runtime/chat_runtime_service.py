from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ai_karen_engine.core.runtime.chat_runtime import get_chat_runtime
from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
    get_chat_runtime_control_plane,
)
from ai_karen_engine.core.logging import get_logger

logger = get_logger(__name__)


class ChatRuntimeService:
    """Thin compatibility facade delegating to canonical runtime interfaces.

    New call sites should use ``ChatRuntime``, ``WorkflowRuntime``, or
    ``ChatRuntimeControlPlane`` directly. This class preserves the legacy
    ``execute`` / ``execute_stream`` entry points during the RC1.3 migration.
    """

    async def ensure_control_plane_ready(
        self,
        user_context: Optional[dict[str, Any]] = None,
        user_id: Optional[str] = None,
        message: Optional[str] = None,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ):
        """Ensure the control plane is ready for chat operations."""
        control_plane = await get_chat_runtime_control_plane()
        ctx = dict(user_context or {})
        if user_id:
            ctx["user_id"] = user_id
        if message:
            ctx["message"] = message
        if session_id:
            ctx["session_id"] = session_id
        if correlation_id:
            ctx["correlation_id"] = correlation_id
        return await control_plane.get_runtime_response(user_context=ctx)

    async def execute(self, request):
        """Delegate canonical chat execution to the single chat runtime."""
        return await get_chat_runtime().execute(request)

    async def execute_stream(self, request):
        """Delegate canonical streaming chat execution to the single chat runtime."""
        return get_chat_runtime().execute_stream(request)


_chat_runtime_service: Optional[ChatRuntimeService] = None


def get_chat_runtime_service() -> ChatRuntimeService:
    global _chat_runtime_service
    if _chat_runtime_service is None:
        _chat_runtime_service = ChatRuntimeService()
    return _chat_runtime_service
