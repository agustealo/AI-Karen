from __future__ import annotations

import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatExecutionResult,
    ChatExecutionStatus,
    ChatRuntimeMetadata,
)
from ai_karen_engine.core.runtime.cortex_execution_decider import (
    get_cortex_execution_decider,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.workflow_runtime import get_workflow_runtime
from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
    DegradedResponse,
    EmergencyFallbackResponse,
    MaintenanceResponse,
    get_chat_runtime_control_plane,
)
from ai_karen_engine.models.shared_types import ChatStreamChunk
from ai_karen_engine.utils.chat_helpers import normalize_session_id as normalize_chat_session_id
from ai_karen_engine.core.expression.gateway import ExpressionGateway
from ai_karen_engine.core.expression.contracts import ExpressionTask

logger = get_logger(__name__)

GATE_RESPONSES = (MaintenanceResponse, EmergencyFallbackResponse, DegradedResponse)

# Canonical runtime metadata keys — these must never be overwritten by
# arbitrary provider/extension metadata (RC1.2.6 hardening direction).
_CANONICAL_META_KEYS = (
    "requested_provider",
    "requested_model",
    "actual_provider",
    "actual_model",
    "runtime_engine",
    "response_source",
    "fallback_level",
    "degraded_mode",
    "degradation_reason",
)


class ChatRuntime:
    """Single authoritative chat execution runtime.

    Every transport delegates here. This runtime owns the pipeline and routes
    execution based on a CORTEX-produced :class:`ExecutionDecision`:

    * simple (``graph_required == False``) -> ExpressionGateway (no LangGraph)
    * graph-required -> WorkflowRuntime/LangGraph adapter

    The runtime stays framework-neutral for the simple path: LangChain/LangGraph
    conversion lives inside the WorkflowRuntime adapter only.
    """

    async def execute(self, request: ChatExecutionRequest) -> ChatExecutionResult:
        start = time.time()
        ctx = request.context

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

        decision = await self._decide(request)
        try:
            if decision.is_graph_required:
                text, provider_meta = await self._run_graph(request)
            else:
                text, provider_meta = await self._run_simple(request)
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
        metadata = self._build_metadata(request, decision, provider_meta, latency_ms)

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

        decision = await self._decide(request)
        gen = (
            self._run_graph_stream(request)
            if decision.is_graph_required
            else self._run_simple_stream(request)
        )
        async for chunk in gen:
            yield chunk

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    async def _decide(self, request: ChatExecutionRequest) -> ExecutionDecision:
        return await get_cortex_execution_decider().decide(request)

    async def _run_simple(
        self, request: ChatExecutionRequest
    ) -> Tuple[str, Dict[str, Any]]:
        """Simple conversational path: CORTEX -> ExpressionGateway.

        No LangGraph, no LangChain. Returns (answer, normalized_metadata).
        """
        ctx = request.context
        gateway = ExpressionGateway()
        task = ExpressionTask(
            task_id=f"expr_{ctx.correlation_id}",
            kind="chat",
            messages=request.messages,
            response_mode="text",
            required_capabilities=[],
            forbidden_capabilities=[],
            preferred_provider=request.preferred_provider,
            preferred_model=request.preferred_model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            timeout_ms=30000,
            correlation_id=ctx.correlation_id,
            request_id=ctx.request_id,
            metadata={
                "transport": request.metadata.get("transport", "runtime"),
                "execution_mode": "direct",
            },
        )
        result = await gateway.generate(task)

        normalized = {
            "requested_provider": request.preferred_provider,
            "requested_model": request.preferred_model,
            "actual_provider": result.provider,
            "actual_model": result.model,
            "runtime_engine": result.runtime_engine or result.engine_id,
            "response_source": result.response_source,
            "fallback_level": (result.metadata or {}).get("fallback_level", 0),
            "degraded_mode": result.degraded,
            "degradation_reason": result.degradation_reason,
        }
        return result.text, normalized

    async def _run_simple_stream(
        self, request: ChatExecutionRequest
    ) -> AsyncIterator[ChatStreamChunk]:
        ctx = request.context
        try:
            text, normalized = await self._run_simple(request)
            yield ChatStreamChunk(
                type="content",
                content=text,
                correlation_id=ctx.correlation_id,
                metadata={
                    "execution_mode": "direct",
                    "actual_provider": normalized.get("actual_provider"),
                    "actual_model": normalized.get("actual_model"),
                    "response_source": normalized.get("response_source"),
                },
            )
        except Exception as exc:  # pragma: no cover - defensive runtime boundary
            logger.error(
                "ChatRuntime simple stream failed: %s",
                exc,
                extra={"correlation_id": ctx.correlation_id},
            )
            yield ChatStreamChunk(
                type="error",
                content=str(exc),
                correlation_id=ctx.correlation_id,
                metadata={"event": "error"},
            )
        finally:
            yield ChatStreamChunk(
                type="complete",
                content="",
                correlation_id=ctx.correlation_id,
                metadata={
                    "session_id": ctx.conversation_id
                    or normalize_chat_session_id(ctx.session_id)
                },
            )

    async def _run_graph(
        self, request: ChatExecutionRequest
    ) -> Tuple[str, Dict[str, Any]]:
        """Graph-required path: routed exclusively through WorkflowRuntime."""
        text, response_metadata = await get_workflow_runtime().run(request)
        return text, self._normalize_graph_meta(response_metadata, request)

    async def _run_graph_stream(
        self, request: ChatExecutionRequest
    ) -> AsyncIterator[ChatStreamChunk]:
        async for chunk in get_workflow_runtime().stream(request):
            yield chunk

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _normalize_graph_meta(
        self, response_metadata: Dict[str, Any], request: ChatExecutionRequest
    ) -> Dict[str, Any]:
        raw = response_metadata or {}
        llm = raw.get("llm_metadata") or {}
        return {
            "requested_provider": llm.get("requested_provider")
            or request.preferred_provider,
            "requested_model": llm.get("requested_model") or request.preferred_model,
            "actual_provider": llm.get("actual_provider"),
            "actual_model": llm.get("actual_model"),
            "runtime_engine": llm.get("runtime_engine"),
            "response_source": llm.get("response_source"),
            "fallback_level": llm.get("fallback_level", 0),
            "degraded_mode": bool(llm.get("degraded_mode")),
            "degradation_reason": llm.get("degradation_reason"),
            "llm": raw.get("llm"),
        }

    def _build_metadata(
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        normalized: Dict[str, Any],
        latency_ms: float,
    ) -> ChatRuntimeMetadata:
        ctx = request.context
        conversation_id = ctx.conversation_id or normalize_chat_session_id(
            ctx.session_id
        )
        md = ChatRuntimeMetadata(
            correlation_id=ctx.correlation_id,
            latency_ms=latency_ms,
            requested_provider=request.preferred_provider,
            requested_model=request.preferred_model,
            mode="graph" if decision.is_graph_required else "normal",
            response_id=ctx.request_id,
            conversation_id=conversation_id,
        )
        # Set canonical fields from normalized metadata (never overwritten by extras).
        for key in _CANONICAL_META_KEYS:
            value = normalized.get(key)
            if value is not None:
                setattr(md, key, value)
        # Everything else is non-canonical extension metadata.
        md.extra.update(
            {k: v for k, v in normalized.items() if k not in _CANONICAL_META_KEYS}
        )
        return md

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


_chat_runtime: Optional[ChatRuntime] = None


def get_chat_runtime() -> ChatRuntime:
    """Return the singleton authoritative chat runtime."""
    global _chat_runtime
    if _chat_runtime is None:
        _chat_runtime = ChatRuntime()
    return _chat_runtime
