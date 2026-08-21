from __future__ import annotations

import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.models.shared_types import ChatStreamChunk as _SharedChatStreamChunk

logger = get_logger(__name__)


class WorkflowRuntime:
    """Graph-required execution adapter.

    This is the *only* place LangGraph/LangChain is touched for chat. It is
    invoked exclusively when CORTEX decides ``graph_required == True``.

    LangChain message conversion lives here so the canonical ``ChatRuntime``
    stays framework-neutral for simple chat.
    """

    async def run(self, request: ChatExecutionRequest) -> Tuple[str, Dict[str, Any]]:
        ctx = request.context
        conversation_id = ctx.conversation_id or _normalize(ctx.session_id)
        config = self._build_config(request, ctx, conversation_id)

        orchestrator = await self._get_orchestrator()
        final_state = await orchestrator.process(
            messages=self._to_langchain(request.messages),
            user_id=ctx.user_id,
            session_id=conversation_id,
            config=config,
        )
        return self._extract_payload(final_state)

    async def stream(
        self, request: ChatExecutionRequest
    ) -> AsyncIterator[_SharedChatStreamChunk]:
        ctx = request.context
        conversation_id = ctx.conversation_id or _normalize(ctx.session_id)
        config = self._build_config(request, ctx, conversation_id)

        try:
            orchestrator = await self._get_orchestrator()
            async for chunk in orchestrator.stream_process(
                messages=self._to_langchain(request.messages),
                user_id=ctx.user_id,
                session_id=conversation_id,
                config=config,
            ):
                content, meta = self._extract_stream_payload(chunk)
                if content or meta:
                    yield _SharedChatStreamChunk(
                        type=(
                            "status"
                            if meta.get("status") and not content
                            else "content"
                        ),
                        content=content,
                        correlation_id=ctx.correlation_id,
                        metadata=meta,
                    )
        except Exception as exc:  # pragma: no cover - defensive adapter boundary
            logger.error(
                "WorkflowRuntime.stream failed: %s",
                exc,
                extra={"correlation_id": ctx.correlation_id},
            )
            yield _SharedChatStreamChunk(
                type="error",
                content=str(exc),
                correlation_id=ctx.correlation_id,
                metadata={"event": "error"},
            )

        yield _SharedChatStreamChunk(
            type="complete",
            content="",
            correlation_id=ctx.correlation_id,
            metadata={"session_id": conversation_id},
        )

    # ------------------------------------------------------------------
    # LangGraph-bound helpers (kept inside the adapter on purpose)
    # ------------------------------------------------------------------

    async def _get_orchestrator(self):
        from ai_karen_engine.core.langgraph_orchestrator import get_default_orchestrator

        return await get_default_orchestrator()

    def _build_config(
        self,
        request: ChatExecutionRequest,
        ctx: ChatExecutionContext,
        conversation_id: str,
    ) -> Dict[str, Any]:
        response_id = ctx.request_id or str(uuid.uuid4())
        request_config = {
            "preferred_llm_provider": request.preferred_provider,
            "preferred_model": request.preferred_model,
            "provider": request.preferred_provider,
            "model": request.preferred_model,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "messages": request.messages,
            "response_id": response_id,
        }
        request_config.update(request.metadata or {})
        return {
            "model": request.preferred_model,
            "provider": request.preferred_provider,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "correlation_id": ctx.correlation_id,
            "request_config": request_config,
        }

    def _to_langchain(self, messages: List[Dict[str, Any]]) -> List[BaseMessage]:
        converted: List[BaseMessage] = []
        for msg in messages:
            content = str(msg.get("content") or "")
            message_type = str(msg.get("message_type") or "user").lower()
            if message_type == "assistant":
                converted.append(AIMessage(content=content))
            elif message_type == "system":
                converted.append(SystemMessage(content=content))
            else:
                converted.append(HumanMessage(content=content))
        return converted

    def _extract_payload(self, state: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        formatted = state.get("formatted_response")
        if formatted is not None:
            if hasattr(formatted, "data"):
                data = getattr(formatted, "data") or {}
                metadata = getattr(formatted, "metadata") or {}
                text = str(data.get("response") or data.get("content") or "")
                return text, metadata
            if isinstance(formatted, dict):
                data = formatted.get("data") or {}
                metadata = formatted.get("metadata") or {}
                text = str(data.get("response") or data.get("content") or "")
                return text, metadata
        return self._extract_from_raw(state)

    def _extract_from_raw(self, state: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        text = str(state.get("response") or state.get("llm_response") or "")
        return text, dict(state.get("response_metadata") or {})

    def _extract_stream_payload(self, chunk: Any) -> Tuple[str, Dict[str, Any]]:
        if isinstance(chunk, dict):
            for state_update in chunk.values():
                if not isinstance(state_update, dict):
                    continue
                if "formatted_response" in state_update or "llm_response" in state_update:
                    return self._extract_payload(state_update)
                if "error" in state_update:
                    return f"Error: {state_update['error']}", {
                        "error": state_update["error"]
                    }
        if isinstance(chunk, str):
            return chunk, {}
        return "", {}


def _normalize(session_id: Optional[str]) -> str:
    from ai_karen_engine.utils.chat_helpers import normalize_session_id

    return normalize_session_id(session_id)


_workflow_runtime: Optional[WorkflowRuntime] = None


def get_workflow_runtime() -> WorkflowRuntime:
    """Return the singleton graph-required workflow runtime adapter."""
    global _workflow_runtime
    if _workflow_runtime is None:
        _workflow_runtime = WorkflowRuntime()
    return _workflow_runtime
