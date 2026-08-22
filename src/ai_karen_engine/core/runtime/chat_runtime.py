from __future__ import annotations

import asyncio
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
from ai_karen_engine.core.runtime.runtime_fallback import build_runtime_fallback
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
    """Single authoritative chat execution runtime."""

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

        memory_recall_meta: Dict[str, Any] = {}
        if decision.memory_recall_required:
            memory_recall_meta = await self._recall_memory(request, decision)

        try:
            if decision.is_graph_required:
                text, provider_meta = await self._run_graph(request, decision)
            else:
                text, provider_meta = await self._run_simple(request, decision)
        except Exception as exc:
            logger.error(
                "ChatRuntime.execute failed, attempting fallback: %s",
                exc,
                extra={"correlation_id": ctx.correlation_id},
            )
            conversation_id = ctx.conversation_id or normalize_chat_session_id(
                ctx.session_id
            )
            fallback = await build_runtime_fallback(runtime=self,
                request=request,
                failure=exc,
                correlation_id=ctx.correlation_id,
                conversation_id=conversation_id,
                start_time=start,
                decision=decision,
            )
            if fallback is not None and fallback.answer:
                await self._persist_memory(request, fallback.answer, memory_recall_meta, decision)
                return self._build_result(request, decision, provider_meta or {}, start, memory_recall_meta, fallback.answer)
            return ChatExecutionResult(
                answer="",
                status=ChatExecutionStatus.ERROR,
                metadata=ChatRuntimeMetadata(
                    correlation_id=ctx.correlation_id,
                    latency_ms=(time.time() - start) * 1000.0,
                    mode="emergency",
                    degraded_mode=True,
                    degradation_reason=f"all_execution_paths_failed:{type(exc).__name__}",
                ),
            )

        await self._persist_memory(request, text, memory_recall_meta, decision)

        latency_ms = (time.time() - start) * 1000.0
        return self._build_result(request, decision, provider_meta, start, memory_recall_meta, text, latency_ms)

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

        memory_recall_meta: Dict[str, Any] = {}
        if decision.memory_recall_required:
            memory_recall_meta = await self._recall_memory(request, decision)

        streamed_text = ""
        gen = (
            self._run_graph_stream(request, decision)
            if decision.is_graph_required
            else self._run_simple_stream(request, decision)
        )
        async for chunk in gen:
            if chunk.type == "content":
                streamed_text += chunk.content
            yield chunk

        if decision.memory_recall_required and decision.memory_write_allowed:
            try:
                await self._persist_memory(request, streamed_text, memory_recall_meta, decision)
            except Exception as exc:
                logger.warning("Streaming memory persistence failed: %s", exc)

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    async def _recall_memory(
        self, request: ChatExecutionRequest, decision: ExecutionDecision
    ) -> Dict[str, Any]:
        ctx = request.context
        user_message = self._extract_user_message(request.messages)

        meta: Dict[str, Any] = {
            "memory_recall_status": "skipped",
            "memory_recall_count": 0,
            "memory_latency_ms": 0.0,
            "memory_persistence_status": "skipped",
            "memory_degraded": False,
            "memory_degradation_reason": None,
        }

        try:
            from ai_karen_engine.core.memory import get_memory_manager

            mem = get_memory_manager()
            recall_start = time.time()
            result = await mem.recall_context(
                user_id=ctx.user_id,
                tenant_id=ctx.tenant_id,
                query=user_message,
                top_k=decision.memory_top_k,
                session_id=ctx.session_id,
                conversation_id=ctx.conversation_id,
                correlation_id=ctx.correlation_id,
            )
            recall_ms = (time.time() - recall_start) * 1000.0

            items = result.get("results") or []
            meta.update({
                "memory_recall_status": result.get("status", "success"),
                "memory_recall_count": len(items),
                "memory_latency_ms": recall_ms,
                "memory_degraded": result.get("status") == "degraded",
                "memory_degradation_reason": result.get("error") or result.get("reason"),
            })

            if items:
                ctx.metadata = ctx.metadata or {}
                ctx.metadata.setdefault("memory_context", {})
                ctx.metadata["memory_context"]["recall"] = [
                    {"id": i.get("id"), "content": i.get("content"), "timestamp": i.get("timestamp")}
                    for i in items[:5]
                ]

        except Exception as exc:
            logger.warning("Memory recall failed: %s", exc, extra={"correlation_id": ctx.correlation_id})
            meta.update({
                "memory_recall_status": "failed",
                "memory_degraded": True,
                "memory_degradation_reason": str(exc),
            })

        return meta

    async def _persist_memory(
        self,
        request: ChatExecutionRequest,
        response_text: str,
        memory_recall_meta: Dict[str, Any],
        decision: ExecutionDecision,
    ) -> None:
        if not decision.memory_write_allowed:
            memory_recall_meta["memory_persistence_status"] = "denied_by_policy"
            return

        if memory_recall_meta.get("memory_degraded") and memory_recall_meta.get("memory_recall_status") == "failed":
            memory_recall_meta["memory_persistence_status"] = "skipped_degraded_recall"
            return

        ctx = request.context
        try:
            from ai_karen_engine.core.memory import get_memory_manager

            mem = get_memory_manager()
            user_message = self._extract_user_message(request.messages)

            if user_message.strip():
                await mem.process_interaction(
                    text=user_message,
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                    source_type="chat_user",
                    source_ref=ctx.conversation_id or ctx.session_id,
                    metadata={
                        "correlation_id": ctx.correlation_id,
                        "session_id": ctx.session_id,
                        "conversation_id": ctx.conversation_id,
                        "request_id": ctx.request_id,
                        "response_length": len(response_text or ""),
                        "memory_actor": "user",
                    },
                )

            if response_text.strip() and decision.memory_write_allowed:
                await mem.process_interaction(
                    text=response_text,
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                    source_type="chat_assistant",
                    source_ref=ctx.conversation_id or ctx.session_id,
                    metadata={
                        "correlation_id": ctx.correlation_id,
                        "session_id": ctx.session_id,
                        "conversation_id": ctx.conversation_id,
                        "request_id": ctx.request_id,
                        "is_assistant": True,
                        "memory_actor": "assistant",
                        "memory_promotion_eligible": False,
                    },
                )

            memory_recall_meta["memory_persistence_status"] = "persisted"

        except Exception as exc:
            logger.warning("Memory persistence failed: %s", exc, extra={"correlation_id": ctx.correlation_id})
            memory_recall_meta["memory_persistence_status"] = "failed"
            memory_recall_meta["memory_degraded"] = True
            memory_recall_meta["memory_degradation_reason"] = str(exc)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    async def _decide(self, request: ChatExecutionRequest) -> ExecutionDecision:
        return await get_cortex_execution_decider().decide(request)

    async def _run_simple(
        self, request: ChatExecutionRequest, decision: ExecutionDecision
    ) -> Tuple[str, Dict[str, Any]]:
        """Simple conversational path: CORTEX -> ExpressionGateway."""
        ctx = request.context
        gateway = ExpressionGateway()
        task = ExpressionTask(
            task_id=f"expr_{ctx.correlation_id}",
            kind="chat",
            messages=await self._assemble_prompt(request, decision),
            response_mode="text",
            required_capabilities=list(decision.required_capabilities),
            forbidden_capabilities=list(decision.forbidden_capabilities),
            preferred_provider=request.preferred_provider,
            preferred_model=request.preferred_model,
            max_tokens=request.max_tokens or decision.token_budget,
            temperature=request.temperature,
            timeout_ms=decision.time_budget_ms,
            correlation_id=ctx.correlation_id,
            request_id=ctx.request_id,
            metadata={
                "transport": request.metadata.get("transport", "runtime"),
                "execution_mode": "direct",
                "reasoning_depth": decision.reasoning_depth,
                "memory_context": (ctx.metadata or {}).get("memory_context", {}),
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
        self, request: ChatExecutionRequest, decision: ExecutionDecision
    ) -> AsyncIterator[ChatStreamChunk]:
        ctx = request.context
        try:
            text, normalized = await self._run_simple(request, decision)
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
        except Exception as exc:
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
        self, request: ChatExecutionRequest, decision: ExecutionDecision
    ) -> Tuple[str, Dict[str, Any]]:
        """Graph-required path: routed exclusively through WorkflowRuntime."""
        text, response_metadata = await get_workflow_runtime().run(request, decision)
        return text, self._normalize_graph_meta(response_metadata, request)

    async def _run_graph_stream(
        self, request: ChatExecutionRequest, decision: ExecutionDecision
    ) -> AsyncIterator[ChatStreamChunk]:
        async for chunk in get_workflow_runtime().stream(request, decision):
            yield chunk

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _assemble_prompt(
        self, request: ChatExecutionRequest, decision: ExecutionDecision
    ) -> List[Dict[str, Any]]:
        """Assemble prompt using canonical PromptRuntime.

        Memory recall, persona, policy, tools, and workflow context are
        assembled into the final message list sent to ExpressionGateway.
        """
        from ai_karen_engine.core.runtime.prompt import (
            PromptAssemblyRequest,
            get_prompt_assembler,
        )

        ctx = request.context
        memory_context = (ctx.metadata or {}).get("memory_context", {})
        recall_items = memory_context.get("recall", [])

        assembly_request = PromptAssemblyRequest(
            prompt_id="karen-chat",
            prompt_version="v1",
            memory_items=recall_items if decision.memory_recall_required else [],
            tool_contracts=[
                {"name": name, "description": ""}
                for name in decision.tool_requirements
            ],
            workflow_context={
                "workflow_id": decision.workflow_id,
                "workflow_version": decision.workflow_version,
                "requires_human_gate": decision.requires_human_gate,
                "requires_resumability": decision.requires_resumability,
            },
            token_budget=decision.token_budget,
            messages=[dict(msg) for msg in request.messages],
        )

        result = await get_prompt_assembler().assemble(assembly_request)
        return result.messages

    def _extract_user_message(self, messages: List[Dict[str, Any]]) -> str:
        """Extract the latest user message."""
        if not messages:
            return ""
        for msg in reversed(messages):
            role = str(msg.get("role", "")).lower()
            if role == "user":
                return str(msg.get("content", ""))
        return str(messages[-1].get("content", ""))

    def _build_result(
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        normalized: Dict[str, Any],
        start: float,
        memory_meta: Dict[str, Any],
        text: str,
        latency_ms: Optional[float] = None,
    ) -> ChatExecutionResult:
        ctx = request.context
        conversation_id = ctx.conversation_id or normalize_chat_session_id(
            ctx.session_id
        )
        if latency_ms is None:
            latency_ms = (time.time() - start) * 1000.0

        md = self._build_metadata(request, decision, normalized, latency_ms, memory_meta)

        status = ChatExecutionStatus.OK
        if md.degraded_mode or memory_meta.get("memory_degraded"):
            status = ChatExecutionStatus.DEGRADED
        if normalized.get("degradation_reason") and "all_execution_paths_failed" in str(normalized.get("degradation_reason")):
            status = ChatExecutionStatus.ERROR

        return ChatExecutionResult(
            answer=text,
            status=status,
            metadata=md,
            structured_content=dict(normalized.get("structured_content") or {}),
        )

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
        memory_meta: Optional[Dict[str, Any]] = None,
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
        for key in _CANONICAL_META_KEYS:
            value = normalized.get(key)
            if value is not None:
                setattr(md, key, value)

        if memory_meta:
            md.extra.update({k: v for k, v in memory_meta.items() if k not in md.extra})

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
