from __future__ import annotations

import asyncio
import datetime
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
    ChatStreamEventType,
)
from ai_karen_engine.core.runtime.contracts import (
    ActionExecutionGate,
    AuthorizedExecutionPlan,
    DegradationState,
    ExecutionBudget,
    ExecutionBudgetMeter,
    ExecutionContext,
    ExecutionTopology,
    ResponseProvenance,
    ResponseSource,
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
from ai_karen_engine.core.runtime.trajectory.recorder import TrajectoryRecorder
from ai_karen_engine.core.runtime.outcome.recorder import OutcomeRecorder
from ai_karen_engine.core.observability.emitter import get_observability_emitter
from ai_karen_engine.core.observability.contracts import RuntimeEventType
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatStreamChunk
from ai_karen_engine.utils.chat_helpers import normalize_session_id as normalize_chat_session_id
from ai_karen_engine.core.expression.gateway import ExpressionGateway
from ai_karen_engine.core.expression.contracts import ExpressionTask

logger = get_logger(__name__)

GATE_RESPONSES = (MaintenanceResponse, EmergencyFallbackResponse, DegradedResponse)

_CANONICAL_META_KEYS = (
    "requested_provider",
    "requested_model",
    "requested_target",
    "actual_provider",
    "actual_model",
    "actual_target",
    "runtime_engine",
    "protocol",
    "locality",
    "response_source",
    "fallback_level",
    "fallback_reason",
    "failure_category",
    "provider_attempts",
    "degradation_type",
    "degraded_mode",
    "degradation_reason",
)


class ChatRuntime:
    """Single authoritative chat execution runtime."""

    def __init__(self) -> None:
        self._trajectory_recorder = TrajectoryRecorder()
        self._outcome_recorder = OutcomeRecorder()
        self._emitter = get_observability_emitter()

    async def get_orchestrator(self) -> Any:
        """Return the graph orchestrator adapter for health/availability checks."""
        return get_workflow_runtime()

    async def execute(self, request: ChatExecutionRequest) -> ChatExecutionResult:
        start = time.time()
        ctx = request.context

        self._bind_observability_context(ctx)
        self._emitter.emit(
            RuntimeEventType.REQUEST_RECEIVED,
            intent="general_assist",
            metadata={"transport": "http", "message_count": len(request.messages)},
        )

        gate = await self._resolve_gate(ctx)
        if gate is not None:
            self._emitter.emit(
                RuntimeEventType.REQUEST_FAILED,
                status="gate",
                metadata={"gate_mode": getattr(gate, "mode", "gate")},
            )
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
        self._emitter.emit(
            RuntimeEventType.CORTEX_DECISION,
            intent=decision.intent,
            policy_decision_id=decision.policy_decision_id,
            metadata={
                "topology": decision.topology.value,
                "execution_mode": decision.execution_mode.value,
                "reason_codes": decision.reason_codes,
            },
        )

        plan = self._build_authorized_plan(request, decision)
        meter = ExecutionBudgetMeter(plan.budget)
        meter.start()
        trajectory = self._trajectory_recorder.start()

        memory_recall_meta: Dict[str, Any] = {}
        provider_meta: Dict[str, Any] = {}
        if decision.memory_recall_required:
            self._emitter.emit(
                RuntimeEventType.MEMORY_RECALL_STARTED,
                policy_decision_id=decision.policy_decision_id,
            )
            memory_recall_meta = await self._recall_memory(request, decision)
            self._emitter.emit(
                RuntimeEventType.MEMORY_RECALL_COMPLETED,
                policy_decision_id=decision.policy_decision_id,
                memory_recall_count=memory_recall_meta.get("memory_recall_count", 0),
            )
            trajectory.memory_recall_count = memory_recall_meta.get("memory_recall_count")
            trajectory.memory_recall_refs = [
                item.get("id", "")
                for item in (memory_recall_meta.get("memory_context") or {}).get("recall", [])[:5]
                if item.get("id")
            ]

        try:
            if decision.topology.value == "reasoning":
                text, provider_meta = await self._run_reasoning(request, decision, plan, meter)
            elif decision.is_graph_required:
                text, provider_meta = await self._run_graph(request, decision, plan, meter)
            else:
                text, provider_meta = await self._run_simple(request, decision, plan, meter)
        except Exception as exc:
            logger.error(
                "ChatRuntime.execute failed, attempting fallback: %s",
                exc,
                extra={"correlation_id": ctx.correlation_id},
            )
            self._emitter.emit(
                RuntimeEventType.REQUEST_FAILED,
                error_type=type(exc).__name__,
                status="error",
                metadata={"error": str(exc)},
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
                if decision.memory_recall_required:
                    await self._persist_memory(request, fallback.answer, memory_recall_meta, plan)
                self._record_trajectory_completion(trajectory, decision, fallback.answer, start, meter, provider_meta or {}, memory_recall_meta, error=f"fallback:{type(exc).__name__}")
                self._record_execution_outcome(trajectory.trajectory_id, decision, fallback.answer, start, meter, memory_recall_meta, success=False)
                return fallback
            self._record_trajectory_completion(trajectory, decision, "", start, meter, {}, memory_recall_meta, error="all_execution_paths_failed")
            self._record_execution_outcome(trajectory.trajectory_id, decision, "", start, meter, memory_recall_meta, success=False)
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

        if decision.memory_recall_required:
            await self._persist_memory(request, text, memory_recall_meta, plan)

        latency_ms = (time.time() - start) * 1000.0
        self._record_trajectory_completion(trajectory, decision, text, start, meter, provider_meta, memory_recall_meta)
        self._record_execution_outcome(trajectory.trajectory_id, decision, text, start, meter, memory_recall_meta, success=True)

        self._emitter.emit(
            RuntimeEventType.REQUEST_COMPLETED,
            latency_ms=latency_ms,
            provider=provider_meta.get("actual_provider"),
            model=provider_meta.get("actual_model"),
            runtime_engine=provider_meta.get("runtime_engine"),
            response_source=provider_meta.get("response_source"),
            fallback_level=provider_meta.get("fallback_level", 0),
            degraded_mode=provider_meta.get("degraded_mode", False),
            memory_recall_count=memory_recall_meta.get("memory_recall_count", 0),
        )

        return self._build_result(request, decision, provider_meta, start, memory_recall_meta, text, latency_ms)

    async def execute_stream(
        self, request: ChatExecutionRequest
    ) -> AsyncIterator[ChatStreamChunk]:
        ctx = request.context
        sequence = 0
        request_id = ctx.request_id or str(uuid.uuid4())
        response_id = ctx.request_id or str(uuid.uuid4())
        conversation_id = ctx.conversation_id or normalize_chat_session_id(ctx.session_id)

        self._bind_observability_context(ctx)
        self._emitter.emit(
            RuntimeEventType.REQUEST_RECEIVED,
            intent="general_assist",
            metadata={"transport": "stream", "message_count": len(request.messages)},
        )

        gate = await self._resolve_gate(ctx)
        if gate is not None:
            self._emitter.emit(
                RuntimeEventType.REQUEST_FAILED,
                status="gate",
                metadata={"gate_mode": getattr(gate, "mode", "gate")},
            )
            yield self._enrich_chunk(
                ChatStreamChunk(
                    type="error",
                    content=getattr(gate, "message", "Service unavailable"),
                    correlation_id=ctx.correlation_id,
                    metadata={"gate": getattr(gate, "mode", "gate")},
                ),
                sequence,
                request_id,
                response_id,
                conversation_id,
            )
            sequence += 1
            yield self._enrich_chunk(
                ChatStreamChunk(
                    type="complete",
                    content="",
                    correlation_id=ctx.correlation_id,
                    metadata={"gate": getattr(gate, "mode", "gate")},
                ),
                sequence,
                request_id,
                response_id,
                conversation_id,
            )
            sequence += 1
            return

        decision = await self._decide(request)
        plan = self._build_authorized_plan(request, decision)
        meter = ExecutionBudgetMeter(plan.budget)
        meter.start()
        trajectory = self._trajectory_recorder.start()
        stream_start = time.time()

        yield self._enrich_chunk(
            ChatStreamChunk(
                type="status",
                content="Processing request...",
                correlation_id=ctx.correlation_id,
                metadata={"stage": "started"},
            ),
            sequence,
            request_id,
            response_id,
            conversation_id,
        )
        sequence += 1

        memory_recall_meta: Dict[str, Any] = {}
        if decision.memory_recall_required:
            memory_recall_meta = await self._recall_memory(request, decision)
            trajectory.memory_recall_count = memory_recall_meta.get("memory_recall_count")
            trajectory.memory_recall_refs = [
                item.get("id", "")
                for item in (memory_recall_meta.get("memory_context") or {}).get("recall", [])[:5]
                if item.get("id")
            ]

        streamed_text = ""
        provider_meta: Dict[str, Any] = {}
        generation_error: Optional[Exception] = None

        gen = (
            self._run_reasoning_stream(request, decision, plan, meter, _meta=provider_meta)
            if decision.topology.value == "reasoning"
            else (
                self._run_graph_stream(request, decision, plan, meter, _meta=provider_meta)
                if decision.is_graph_required
                else self._run_simple_stream(
                    request, decision, plan, meter, memory_recall_meta, _meta=provider_meta
                )
            )
        )

        try:
            async for chunk in gen:
                if chunk.type == "content":
                    streamed_text += chunk.content
                if chunk.type == ChatStreamEventType.COMPLETE:
                    continue
                yield self._enrich_chunk(chunk, sequence, request_id, response_id, conversation_id)
                sequence += 1
        except asyncio.CancelledError:
            self._emitter.emit(
                RuntimeEventType.REQUEST_CANCELLED,
                correlation_id=ctx.correlation_id,
                request_id=request_id,
                user_id=ctx.user_id,
                tenant_id=ctx.tenant_id,
                session_id=ctx.session_id,
                conversation_id=conversation_id,
            )
            raise
        except Exception as exc:
            generation_error = exc
            logger.error(
                "ChatRuntime stream failed: %s",
                exc,
                extra={"correlation_id": ctx.correlation_id},
            )
            self._emitter.emit(
                RuntimeEventType.REQUEST_FAILED,
                error_type=type(exc).__name__,
                status="error",
                metadata={"error": str(exc)},
            )
            yield self._enrich_chunk(
                ChatStreamChunk(
                    type="error",
                    content=str(exc),
                    correlation_id=ctx.correlation_id,
                    metadata={"error_type": type(exc).__name__},
                ),
                sequence,
                request_id,
                response_id,
                conversation_id,
            )
            sequence += 1

        persistence_failed = False
        if decision.memory_recall_required and decision.memory_write_allowed:
            try:
                await self._persist_memory(request, streamed_text, memory_recall_meta, plan)
            except Exception as exc:
                persistence_failed = True
                logger.warning("Streaming memory persistence failed: %s", exc)

        latency_ms = (time.time() - stream_start) * 1000.0
        success = bool(streamed_text) and generation_error is None
        self._record_trajectory_completion(
            trajectory,
            decision,
            streamed_text,
            stream_start,
            meter,
            provider_meta,
            memory_recall_meta,
            error=str(generation_error) if generation_error else None,
        )
        self._record_execution_outcome(
            trajectory.trajectory_id,
            decision,
            streamed_text,
            stream_start,
            meter,
            memory_recall_meta,
            success=success,
        )

        terminal_metadata = self._build_stream_terminal_metadata(
            request,
            decision,
            provider_meta,
            memory_recall_meta,
            latency_ms,
            request_id,
            response_id,
            generation_error=generation_error,
            persistence_failed=persistence_failed,
        )

        self._emitter.emit(
            RuntimeEventType.REQUEST_COMPLETED,
            intent=decision.intent,
            latency_ms=latency_ms,
            provider=provider_meta.get("actual_provider"),
            model=provider_meta.get("actual_model"),
            runtime_engine=provider_meta.get("runtime_engine"),
            response_source=provider_meta.get("response_source"),
            fallback_level=provider_meta.get("fallback_level", 0),
            degraded_mode=provider_meta.get("degraded_mode", False) or persistence_failed,
            memory_recall_count=memory_recall_meta.get("memory_recall_count", 0),
        )

        yield self._enrich_chunk(
            ChatStreamChunk(
                type="complete",
                content="",
                correlation_id=ctx.correlation_id,
                metadata=terminal_metadata,
            ),
            sequence,
            request_id,
            response_id,
            conversation_id,
        )
        sequence += 1

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
                memory_context = (request.metadata or {}).get("memory_context") or {}
                memory_context["recall"] = [
                    {"id": i.get("id"), "content": i.get("content"), "timestamp": i.get("timestamp")}
                    for i in items[:5]
                ]
                request.metadata["memory_context"] = memory_context

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
        plan: AuthorizedExecutionPlan,
    ) -> None:
        if not await ActionExecutionGate.authorize(plan, "memory.write"):
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

            if response_text.strip():
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
            self._emitter.emit(
                RuntimeEventType.PERSISTENCE_COMPLETED,
                policy_decision_id=plan.policy_decision_id,
                metadata={"target": "memory"},
            )

        except Exception as exc:
            logger.warning("Memory persistence failed: %s", exc, extra={"correlation_id": ctx.correlation_id})
            memory_recall_meta["memory_persistence_status"] = "failed"
            memory_recall_meta["memory_degraded"] = True
            memory_recall_meta["memory_degradation_reason"] = str(exc)
            self._emitter.emit(
                RuntimeEventType.PERSISTENCE_FAILED,
                error_type=type(exc).__name__,
                metadata={"target": "memory", "error": str(exc)},
            )

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    async def _decide(self, request: ChatExecutionRequest) -> ExecutionDecision:
        return await get_cortex_execution_decider().decide(request)

    def _build_authorized_plan(
        self, request: ChatExecutionRequest, decision: ExecutionDecision
    ) -> AuthorizedExecutionPlan:
        """Derive the single AuthorizedExecutionPlan for this request.

        Every topology consumes this exact plan. No downstream module
        manufactures its own authorization.
        """
        ctx = request.context
        budget = ExecutionBudget(
            max_duration_ms=decision.time_budget_ms,
            max_model_calls=decision.max_steps,
            max_tool_calls=len(decision.tool_requirements) + 5,
            max_reasoning_steps=decision.max_steps,
            max_output_tokens=request.max_tokens or 4096,
        )
        degradation = DegradationState(
            degraded=decision.execution_mode.value == "degraded",
            reason_code=decision.policy_reason_codes[0] if decision.policy_reason_codes else None,
            level=decision.risk_level.value if hasattr(decision.risk_level, "value") else str(decision.risk_level),
        )
        allowed_caps = list(decision.required_capabilities)
        if decision.memory_write_allowed and "memory.write" not in allowed_caps:
            allowed_caps.append("memory.write")
        return AuthorizedExecutionPlan(
            execution_id=f"exec-{ctx.request_id}",
            policy_decision_id=decision.policy_decision_id or f"policy-{ctx.correlation_id}",
            topology=decision.topology,
            allowed_capabilities=allowed_caps,
            allowed_tools=list(decision.tool_requirements),
            allowed_plugins=list(decision.plugin_candidates),
            budget=budget,
            memory_scope=decision.memory_scope,
            reasoning_modes=[decision.reasoning_depth] if decision.reasoning_depth != "standard" else [],
            workflow_id=decision.workflow_id,
            degraded_allowed=True,
            degradation_state=degradation,
            audit_context={
                "intent": decision.intent,
                "risk_level": decision.risk_level.value if hasattr(decision.risk_level, "value") else str(decision.risk_level),
                "reason_codes": decision.reason_codes,
            },
        )

    async def _run_simple(
        self, request: ChatExecutionRequest, decision: ExecutionDecision, plan: AuthorizedExecutionPlan, meter: ExecutionBudgetMeter, memory_recall_meta: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """Simple conversational path: CORTEX -> ExpressionGateway."""
        if not await meter.consume_model_call():
            raise RuntimeError("Execution budget exhausted: max_model_calls")

        ctx = request.context
        gateway = ExpressionGateway()
        task = ExpressionTask(
            task_id=f"expr_{ctx.correlation_id}",
            kind="chat",
            messages=await self._assemble_prompt(request, decision, memory_recall_meta),
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
                "memory_context": memory_recall_meta.get("memory_context", {}) if hasattr(memory_recall_meta, "get") else {},
                "topology": plan.topology.value,
            },
        )

        self._emitter.emit(
            RuntimeEventType.PROVIDER_SELECTION,
            policy_decision_id=plan.policy_decision_id,
            provider=request.preferred_provider,
            model=request.preferred_model,
            intent=decision.intent,
        )

        result = await gateway.generate(task)

        if not await meter.check_duration():
            raise RuntimeError("Execution budget exhausted: max_duration_ms")

        provenance = ResponseProvenance(
            response_source=ResponseSource.MODEL,
            provider=result.provider,
            model=result.model,
            engine=result.runtime_engine or result.engine_id,
            fallback_level=(result.metadata or {}).get("fallback_level", 0),
            degradation_reason=result.degradation_reason if result.degraded else None,
            correlation_id=ctx.correlation_id,
            decision_id=plan.policy_decision_id,
        )

        normalized = {
            "requested_provider": request.preferred_provider,
            "requested_model": request.preferred_model,
            "requested_target": request.preferred_provider,
            "actual_provider": result.provider,
            "actual_model": result.model,
            "actual_target": result.provider,
            "runtime_engine": result.runtime_engine or result.engine_id,
            "protocol": (result.metadata or {}).get("protocol"),
            "locality": (result.metadata or {}).get("locality"),
            "response_source": result.response_source,
            "fallback_level": (result.metadata or {}).get("fallback_level", 0),
            "fallback_reason": (result.metadata or {}).get("degradation_reason") if result.degraded else None,
            "degraded_mode": result.degraded,
            "degradation_reason": result.degradation_reason,
            "degradation_type": (result.metadata or {}).get("degradation_type"),
            "provider_attempts": getattr(result, "attempts", []) or [],
            "provenance": provenance,
        }
        return result.text, normalized

    async def _run_simple_stream(
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        plan: AuthorizedExecutionPlan,
        meter: ExecutionBudgetMeter,
        memory_recall_meta: Optional[Dict[str, Any]] = None,
        _meta: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[ChatStreamChunk]:
        ctx = request.context
        try:
            text, normalized = await self._run_simple(request, decision, plan, meter, memory_recall_meta)
            if _meta is not None:
                _meta.update(normalized)
            yield ChatStreamChunk(
                type="content",
                content=text,
                correlation_id=ctx.correlation_id,
                metadata={
                    "execution_mode": "direct",
                    "actual_provider": normalized.get("actual_provider"),
                    "actual_model": normalized.get("actual_model"),
                    "response_source": normalized.get("response_source"),
                    "topology": plan.topology.value,
                },
            )
        except Exception as exc:
            logger.error(
                "ChatRuntime simple stream failed: %s",
                exc,
                extra={"correlation_id": ctx.correlation_id},
            )
            self._emitter.emit(
                RuntimeEventType.REQUEST_FAILED,
                error_type=type(exc).__name__,
                status="error",
            )
            yield ChatStreamChunk(
                type="error",
                content=str(exc),
                correlation_id=ctx.correlation_id,
                metadata={"error_type": type(exc).__name__},
            )

    async def _run_graph(
        self, request: ChatExecutionRequest, decision: ExecutionDecision, plan: AuthorizedExecutionPlan, meter: ExecutionBudgetMeter
    ) -> Tuple[str, Dict[str, Any]]:
        """Graph-required path: routed exclusively through WorkflowRuntime."""
        text, response_metadata = await get_workflow_runtime().run(request, decision, plan)
        return text, self._normalize_graph_meta(response_metadata, request)

    async def _run_graph_stream(
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        plan: AuthorizedExecutionPlan,
        meter: ExecutionBudgetMeter,
        _meta: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[ChatStreamChunk]:
        async for chunk in get_workflow_runtime().stream(request, decision, plan):
            if chunk.type == ChatStreamEventType.COMPLETE:
                continue
            if _meta is not None:
                self._accumulate_chunk_metadata(chunk, _meta)
            yield chunk

    async def _run_reasoning(
        self, request: ChatExecutionRequest, decision: ExecutionDecision, plan: AuthorizedExecutionPlan, meter: ExecutionBudgetMeter
    ) -> Tuple[str, Dict[str, Any]]:
        """Reasoning topology path: routed through ReasoningExecutor."""
        from ai_karen_engine.core.reasoning.contracts import (
            ReasoningBudget,
            ReasoningEvidence,
            ReasoningRequest,
        )
        from ai_karen_engine.core.reasoning.executor import get_reasoning_executor

        ctx = request.context
        memory_items = []
        if request.metadata:
            memory_items = (request.metadata or {}).get("memory_context", {}).get("recall") or []
        recall_items = memory_items[: decision.memory_top_k]

        evidence = [
            ReasoningEvidence(
                evidence_id=str(item.get("id", f"mem-{idx}")),
                type="memory",
                source="memory_recall",
                source_ref=str(item.get("timestamp", "")),
                content=str(item.get("content", "")),
                relevance=0.5,
                confidence=0.5,
                tenant_id=ctx.tenant_id,
            )
            for idx, item in enumerate(recall_items[: decision.memory_top_k])
        ]

        canonical_request = ReasoningRequest(
            request_id=ctx.request_id,
            correlation_id=ctx.correlation_id,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            conversation_id=ctx.conversation_id,
            objective=self._extract_user_message(request.messages),
            reasoning_modes=list(decision.required_capabilities) or ["synthesis"],
            evidence=evidence,
            constraints={
                "reasoning_depth": decision.reasoning_depth,
                "tool_requirements": list(decision.tool_requirements),
                "plugin_candidates": list(decision.plugin_candidates),
            },
            policy_decision_id=decision.policy_decision_id or "",
            budget=ReasoningBudget(
                max_reasoning_steps=decision.max_steps,
                max_duration_ms=decision.time_budget_ms,
            ),
            metadata={
                "correlation_id": ctx.correlation_id,
                "request_id": ctx.request_id,
            },
        )

        context = ExecutionContext(
            request_id=ctx.request_id,
            correlation_id=ctx.correlation_id,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            session_id=ctx.session_id,
            conversation_id=ctx.conversation_id,
            policy_decision_id=decision.policy_decision_id,
            budget=plan.budget,
        )

        executor = get_reasoning_executor()
        result = await executor.execute(canonical_request, plan, context)

        text = result.summary or ""
        if not text and result.hypotheses:
            text = "; ".join(h.statement for h in result.hypotheses[:3])

        provider_meta = {
            "requested_provider": request.preferred_provider,
            "requested_model": request.preferred_model,
            "actual_provider": "reasoning_executor",
            "actual_model": "canonical",
            "runtime_engine": "reasoning",
            "response_source": "reasoning",
            "fallback_level": 0,
            "degraded_mode": result.status in ("failed", "budget_exhausted"),
            "degradation_reason": result.diagnostics.get("error") if result.status == "failed" else None,
            "reasoning_id": result.reasoning_id,
            "reasoning_status": result.status,
        }
        return text, provider_meta

    async def _run_reasoning_stream(
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        plan: AuthorizedExecutionPlan,
        meter: ExecutionBudgetMeter,
        _meta: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[ChatStreamChunk]:
        text, normalized = await self._run_reasoning(request, decision, plan, meter)
        if _meta is not None:
            _meta.update(normalized)
        yield ChatStreamChunk(
            type="content",
            content=text,
            correlation_id=request.context.correlation_id,
            metadata={
                "execution_mode": "reasoning",
                "actual_provider": normalized.get("actual_provider"),
                "actual_model": normalized.get("actual_model"),
                "response_source": normalized.get("response_source"),
                "topology": plan.topology.value,
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _assemble_prompt(
        self, request: ChatExecutionRequest, decision: ExecutionDecision, memory_context: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Assemble prompt using canonical PromptRuntime."""
        from ai_karen_engine.core.runtime.prompt import (
            PromptAssemblyRequest,
            get_prompt_assembler,
        )

        ctx = request.context
        recall_items = (memory_context or {}).get("recall", []) if memory_context else []
        if not recall_items and decision.memory_recall_required:
            recall_items = (request.metadata or {}).get("memory_context", {}).get("recall", []) or []

        assembly_request = PromptAssemblyRequest(
            prompt_id="karen.chat.default",
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
        if md.degraded_mode:
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

        if md.fallback_level and md.fallback_level > 0:
            md.used_fallback = True

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

    def _bind_observability_context(self, ctx: ChatExecutionContext) -> None:
        from ai_karen_engine.core.observability.context import bind_observability_context
        bind_observability_context(
            correlation_id=ctx.correlation_id,
            request_id=ctx.request_id,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            session_id=ctx.session_id,
            conversation_id=ctx.conversation_id,
        )

    def _enrich_chunk(
        self,
        chunk: ChatStreamChunk,
        sequence: int,
        request_id: str,
        response_id: str,
        conversation_id: str,
    ) -> ChatStreamChunk:
        now = datetime.datetime.utcnow()
        return ChatStreamChunk(
            type=chunk.type,
            content=chunk.content,
            correlation_id=chunk.correlation_id or "",
            metadata=dict(chunk.metadata or {}),
            event_id=chunk.event_id or str(uuid.uuid4()),
            sequence=sequence,
            request_id=request_id,
            response_id=response_id,
            conversation_id=conversation_id,
            timestamp=chunk.timestamp or now,
        )

    def _accumulate_chunk_metadata(self, chunk: ChatStreamChunk, meta: Dict[str, Any]) -> None:
        chunk_meta = chunk.metadata or {}
        for key in _CANONICAL_META_KEYS:
            value = chunk_meta.get(key)
            if value is not None and key not in meta:
                meta[key] = value
        llm = chunk_meta.get("llm_metadata") or chunk_meta.get("llm")
        if isinstance(llm, dict):
            for key in _CANONICAL_META_KEYS:
                value = llm.get(key)
                if value is not None and key not in meta:
                    meta[key] = value

    def _build_stream_terminal_metadata(
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        provider_meta: Dict[str, Any],
        memory_recall_meta: Dict[str, Any],
        latency_ms: float,
        request_id: str,
        response_id: str,
        generation_error: Optional[Exception] = None,
        persistence_failed: bool = False,
    ) -> Dict[str, Any]:
        ctx = request.context
        conversation_id = ctx.conversation_id or normalize_chat_session_id(ctx.session_id)
        degraded = provider_meta.get("degraded_mode", False) or persistence_failed
        degradation_reason = provider_meta.get("degradation_reason")
        if persistence_failed and not generation_error:
            degraded = True
            degradation_reason = "memory_persistence_failed"

        return {
            "correlation_id": ctx.correlation_id,
            "request_id": request_id,
            "response_id": response_id,
            "conversation_id": conversation_id,
            "assistant_message_id": None,
            "requested_provider": request.preferred_provider,
            "requested_model": request.preferred_model,
            "actual_provider": provider_meta.get("actual_provider"),
            "actual_model": provider_meta.get("actual_model"),
            "runtime_engine": provider_meta.get("runtime_engine"),
            "protocol": provider_meta.get("protocol"),
            "locality": provider_meta.get("locality"),
            "response_source": provider_meta.get("response_source"),
            "fallback_level": provider_meta.get("fallback_level", 0),
            "fallback_reason": provider_meta.get("fallback_reason"),
            "failure_category": self._map_failure_category(provider_meta),
            "provider_attempts": provider_meta.get("provider_attempts", []),
            "used_fallback": provider_meta.get("used_fallback", False)
                or provider_meta.get("fallback_level", 0) > 0,
            "degraded_mode": degraded,
            "degradation_reason": degradation_reason,
            "mode": "graph" if decision.is_graph_required else "normal",
            "latency_ms": latency_ms,
            "memory_recall_count": memory_recall_meta.get("memory_recall_count", 0),
            "memory_recall_status": memory_recall_meta.get("memory_recall_status", "skipped"),
            "memory_persistence_status": memory_recall_meta.get(
                "memory_persistence_status", "skipped"
            ),
            "status": "error" if generation_error else ("degraded" if degraded else "ok"),
        }

    @staticmethod
    def _map_failure_category(provider_meta: Dict[str, Any]) -> Optional[str]:
        degradation_type = provider_meta.get("degradation_type")
        if degradation_type == "provider_unavailable":
            return "provider_unavailable"
        if degradation_type == "fallback_exhausted":
            return "degraded_runtime"
        fallback_level = provider_meta.get("fallback_level", 0)
        if fallback_level > 0:
            return "provider_fallback"
        if provider_meta.get("generation_error"):
            return "degraded_runtime"
        return None

    def _record_trajectory_completion(
        self,
        trajectory: Any,
        decision: ExecutionDecision,
        text: str,
        start: float,
        meter: ExecutionBudgetMeter,
        provider_meta: Dict[str, Any],
        memory_meta: Dict[str, Any],
        error: Optional[str] = None,
    ) -> None:
        trajectory.intent = decision.intent
        trajectory.cortex_decision = {
            "topology": decision.topology.value,
            "execution_mode": decision.execution_mode.value,
            "risk_level": decision.risk_level.value if hasattr(decision.risk_level, "value") else str(decision.risk_level),
            "reason_codes": decision.reason_codes,
        }
        trajectory.policy_decision_id = decision.policy_decision_id
        trajectory.policy_allowed_capabilities = list(decision.required_capabilities)
        trajectory.policy_denied_capabilities = list(decision.forbidden_capabilities)
        trajectory.requested_provider = provider_meta.get("requested_provider")
        trajectory.requested_model = provider_meta.get("requested_model")
        trajectory.actual_provider = provider_meta.get("actual_provider")
        trajectory.actual_model = provider_meta.get("actual_model")
        trajectory.runtime_engine = provider_meta.get("runtime_engine")
        trajectory.fallback_level = provider_meta.get("fallback_level", 0)
        trajectory.degraded_mode = provider_meta.get("degraded_mode", False)
        trajectory.degradation_reason = provider_meta.get("degradation_reason")
        trajectory.latencies = {
            "total_ms": (time.time() - start) * 1000.0,
            "model_calls": float(meter.model_calls),
            "tool_calls": float(meter.tool_calls),
        }
        trajectory.execution_status = "success" if text else "failure"
        trajectory.error_code = error
        trajectory.response_source = provider_meta.get("response_source")
        self._trajectory_recorder.complete(
            trajectory,
            execution_status=trajectory.execution_status,
            error_code=error,
            response_source=provider_meta.get("response_source"),
        )

    def _record_execution_outcome(
        self,
        trajectory_id: Optional[str],
        decision: ExecutionDecision,
        text: str,
        start: float,
        meter: ExecutionBudgetMeter,
        memory_meta: Dict[str, Any],
        success: bool,
    ) -> None:
        from ai_karen_engine.core.runtime.outcome.contracts import ExecutionStatus
        latency_ms = (time.time() - start) * 1000.0
        self._outcome_recorder.record_execution_outcome(
            trajectory_id=trajectory_id,
            status=ExecutionStatus.SUCCESS if success else ExecutionStatus.FAILURE,
            latency_ms=latency_ms,
            fallback_count=0,
            response_completed=bool(text),
            persistence_success=memory_meta.get("memory_persistence_status") == "persisted",
            metadata={
                "topology": decision.topology.value,
                "model_calls": meter.model_calls,
                "tool_calls": meter.tool_calls,
                "reasoning_steps": meter.reasoning_steps,
            },
        )


_chat_runtime: Optional[ChatRuntime] = None


def get_chat_runtime() -> ChatRuntime:
    """Return the singleton authoritative chat runtime."""
    global _chat_runtime
    if _chat_runtime is None:
        _chat_runtime = ChatRuntime()
    return _chat_runtime
