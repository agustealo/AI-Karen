from __future__ import annotations

import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatExecutionResult,
    ChatExecutionStatus,
    ChatRuntimeMetadata,
)
from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
    DegradedResponse,
    EmergencyFallbackResponse,
    MaintenanceResponse,
    get_chat_runtime_control_plane,
)
from ai_karen_engine.models.shared_types import ChatStreamChunk
from ai_karen_engine.utils.chat_helpers import normalize_session_id as normalize_chat_session_id

logger = get_logger(__name__)

# Control-plane decisions that must short-circuit execution.
GATE_RESPONSES = (MaintenanceResponse, EmergencyFallbackResponse, DegradedResponse)


class ChatRuntime:
    """Single authoritative chat execution runtime.

    This is the one chat runtime. Every transport must delegate to
    :meth:`execute` (or :meth:`execute_stream`). No alternate chat runtime
    is permitted.

    The runtime owns the full execution pipeline:

    control-plane gate -> context/correlation -> provider/model resolution ->
    execution path decision (CORTEX/graph-required seam) -> orchestrator or
    gateway execution -> metadata normalization -> final response contract.
    """

    async def execute(self, request: ChatExecutionRequest) -> ChatExecutionResult:
        start = time.time()
        ctx = request.context

        # 1. Control-plane gate: system availability owns whether we proceed.
        gate = await self._resolve_gate(ctx)
        if gate is not None:
            return ChatExecutionResult(
                answer="",
                status=ChatExecutionStatus.GATE,
                gate_response=gate,
                metadata=ChatRuntimeMetadata(
                    correlation_id=ctx.correlation_id,
                    latency_ms=(time.time() - start) * 1000.0,
                    mode=getattr(gate, "mode", "gate"),
                ),
            )

        conversation_id = ctx.conversation_id or normalize_chat_session_id(
            ctx.session_id
        )
        config = self._build_config(request, ctx, conversation_id)

        try:
            orchestrator = await self._get_orchestrator()
            final_state = await orchestrator.process(
                messages=self._to_langchain(request.messages),
                user_id=ctx.user_id,
                session_id=conversation_id,
                config=config,
            )
            text, provider_meta = self._extract_payload(final_state)
        except Exception as exc:  # pragma: no cover - defensive runtime boundary
            logger.error(
                "ChatRuntime.execute failed: %s",
                exc,
                extra={"correlation_id": ctx.correlation_id},
            )
            return ChatExecutionResult(
                answer="",
                status=ChatExecutionStatus.ERROR,
                metadata=ChatRuntimeMetadata(
                    correlation_id=ctx.correlation_id,
                    latency_ms=(time.time() - start) * 1000.0,
                    mode="error",
                    degradation_reason=str(exc)[:300],
                ),
            )

        latency_ms = (time.time() - start) * 1000.0
        metadata = self._build_metadata(
            request, conversation_id, config, provider_meta, latency_ms
        )

        status = (
            ChatExecutionStatus.DEGRADED
            if metadata.degraded_mode
            else ChatExecutionStatus.OK
        )
        return ChatExecutionResult(
            answer=text,
            status=status,
            metadata=metadata,
            structured_content=dict(provider_meta.get("structured_content") or {}),
        )

    async def execute_stream(
        self, request: ChatExecutionRequest
    ) -> AsyncIterator[ChatStreamChunk]:
        ctx = request.context

        gate = await self._resolve_gate(ctx)
        if gate is not None:
            yield ChatStreamChunk(
                type="error",
                content=getattr(gate, "message", "Service unavailable"),
                correlation_id=ctx.correlation_id,
                metadata={"gate": getattr(gate, "mode", "gate")},
            )
            return

        conversation_id = ctx.conversation_id or normalize_chat_session_id(
            ctx.session_id
        )
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
                    yield ChatStreamChunk(
                        type=(
                            "status"
                            if meta.get("status") and not content
                            else "content"
                        ),
                        content=content,
                        correlation_id=ctx.correlation_id,
                        metadata=meta,
                    )
        except Exception as exc:  # pragma: no cover - defensive runtime boundary
            logger.error(
                "ChatRuntime.execute_stream failed: %s",
                exc,
                extra={"correlation_id": ctx.correlation_id},
            )
            yield ChatStreamChunk(
                type="error",
                content=str(exc),
                correlation_id=ctx.correlation_id,
                metadata={"event": "error"},
            )

        yield ChatStreamChunk(
            type="complete",
            content="",
            correlation_id=ctx.correlation_id,
            metadata={"session_id": conversation_id},
        )

    # ------------------------------------------------------------------
    # Internal pipeline helpers
    # ------------------------------------------------------------------

    async def _resolve_gate(self, ctx: ChatExecutionContext):
        control_plane = await get_chat_runtime_control_plane()
        gate_ctx = {
            "user_id": ctx.user_id,
            "tenant_id": ctx.tenant_id,
            "session_id": ctx.session_id,
            "correlation_id": ctx.correlation_id,
        }
        gate = await control_plane.get_runtime_response(user_context=gate_ctx)
        if gate is not None and isinstance(gate, GATE_RESPONSES):
            return gate
        return None

    async def _get_orchestrator(self):
        # RC1.2 (LangGraph containment) will replace this unconditional
        # resolution with a CORTEX-driven graph-required decision. For RC1.1
        # the runtime remains the single entry point and preserves behavior.
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

    def _extract_payload(self, state: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
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
        text = str(state.get("response") or state.get("llm_response") or "")
        metadata = dict(state.get("response_metadata") or {})
        return text, metadata

    def _extract_stream_payload(self, chunk: Any) -> tuple[str, Dict[str, Any]]:
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

    def _build_metadata(
        self,
        request: ChatExecutionRequest,
        conversation_id: str,
        config: Dict[str, Any],
        provider_meta: Dict[str, Any],
        latency_ms: float,
    ) -> ChatRuntimeMetadata:
        response_id = (config.get("request_config") or {}).get("response_id")
        metadata = ChatRuntimeMetadata(
            correlation_id=request.context.correlation_id,
            latency_ms=latency_ms,
            requested_provider=request.preferred_provider,
            requested_model=request.preferred_model,
            mode="normal",
            response_id=response_id,
            conversation_id=conversation_id,
        )
        provider_meta = provider_meta or {}
        metadata.extra.update(provider_meta)

        llm_metadata = provider_meta.get("llm") or {}
        raw_llm = provider_meta.get("llm_metadata") or {}
        if raw_llm:
            llm_metadata = raw_llm

        if llm_metadata:
            metadata.requested_provider = llm_metadata.get("requested_provider")
            metadata.actual_provider = llm_metadata.get("actual_provider")
            metadata.requested_model = llm_metadata.get("requested_model")
            metadata.actual_model = llm_metadata.get("actual_model")
            metadata.runtime_engine = llm_metadata.get("runtime_engine")
            metadata.response_source = llm_metadata.get("response_source")
            metadata.fallback_level = llm_metadata.get("fallback_level", 0)
            metadata.used_fallback = bool(llm_metadata.get("used_fallback"))
            if llm_metadata.get("degraded_mode"):
                metadata.degraded_mode = True

        # Preserve any explicit provider/model defaults when missing.
        if metadata.requested_provider is None:
            metadata.requested_provider = config.get("provider")
        if metadata.requested_model is None:
            metadata.requested_model = config.get("model")
        return metadata


_chat_runtime: Optional[ChatRuntime] = None


def get_chat_runtime() -> ChatRuntime:
    """Return the singleton authoritative chat runtime."""
    global _chat_runtime
    if _chat_runtime is None:
        _chat_runtime = ChatRuntime()
    return _chat_runtime
