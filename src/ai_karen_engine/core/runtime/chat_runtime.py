from __future__ import annotations

import asyncio
import datetime
import hashlib
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
from ai_karen_engine.core.runtime.composition import (
    RuntimeComposition,
    get_runtime_composition,
)
from ai_karen_engine.core.runtime.consumer_insights import build_consumer_insights
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    ConversationRuntimeGateway,
    TranscriptPersistenceResult,
    get_conversation_runtime_gateway,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.workflow_runtime import get_workflow_runtime
from ai_karen_engine.core.runtime.runtime_fallback import build_runtime_fallback
from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
    ApprovalRequiredResponse,
    DegradedResponse,
    EmergencyFallbackResponse,
    MaintenanceResponse,
    get_chat_runtime_control_plane,
)
from ai_karen_engine.core.runtime.trajectory.learning_contracts import (
    DecisionType,
    OpeEligibilityReason,
    PROACTIVE_CONTINUITY_FEATURES_V1,
    PROACTIVE_CONTINUITY_POLICY_ID,
    PROACTIVE_CONTINUITY_POLICY_VERSION,
    TOPOLOGY_FEATURES_V1,
)
from ai_karen_engine.core.runtime.trajectory.recorder import TrajectoryRecorder
from ai_karen_engine.core.runtime.outcome.recorder import OutcomeRecorder
from ai_karen_engine.platform.observability import get_observability_emitter
from ai_karen_engine.platform.observability.contracts import EventType as RuntimeEventType
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatStreamChunk
from ai_karen_engine.core.expression.contracts import ExpressionTask
from ai_karen_engine.services.approvals import (
    ApprovalError,
    get_approval_service,
)

logger = get_logger(__name__)

GATE_RESPONSES = (
    MaintenanceResponse,
    EmergencyFallbackResponse,
    DegradedResponse,
    ApprovalRequiredResponse,
)

_RICH_RESULT_KEYS = (
    "structured_content",
    "actions",
    "citations",
    "sources",
    "attachments",
    "artifacts",
)

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

    def __init__(
        self,
        *,
        composition: Optional[RuntimeComposition] = None,
        conversation_gateway: Optional[ConversationRuntimeGateway] = None,
    ) -> None:
        self._composition = composition or get_runtime_composition()
        self._conversation_gateway = conversation_gateway
        self._trajectory_recorder = TrajectoryRecorder(
            store=self._composition.trajectory_store
        )
        self._outcome_recorder = OutcomeRecorder(store=self._composition.outcome_store)
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
        await self._record_user_behavior_observation(request, decision)
        self._emitter.emit(
            RuntimeEventType.CORTEX_DECISION,
            intent=decision.intent,
            policy_decision_id=decision.policy_decision_id,
            metadata={
                "topology": decision.topology.value,
                "execution_mode": decision.execution_mode.value,
                "reason_codes": decision.reason_codes,
                "reasoning_modes": list(decision.reasoning_modes),
                "max_model_calls": decision.max_model_calls,
            },
        )

        plan = self._build_authorized_plan(request, decision)
        approval_gate = await self._resolve_human_approval_gate(request, decision)
        if approval_gate is not None:
            self._emitter.emit(
                RuntimeEventType.REQUEST_FAILED,
                status="approval_required",
                intent=decision.intent,
                policy_decision_id=decision.policy_decision_id,
                metadata={
                    "approval_id": approval_gate.approval_id,
                    "approval_status": approval_gate.status,
                },
            )
            return ChatExecutionResult(
                answer="",
                status=ChatExecutionStatus.GATE,
                gate_response=approval_gate,
                metadata=ChatRuntimeMetadata(
                    correlation_id=ctx.correlation_id,
                    latency_ms=(time.time() - start) * 1000.0,
                    mode=approval_gate.mode,
                    extra={
                        "approval_id": approval_gate.approval_id,
                        "approval_status": approval_gate.status,
                    },
                ),
            )
        meter = ExecutionBudgetMeter(plan.budget)
        meter.start()
        trajectory = self._trajectory_recorder.start()
        decision_observation_id = await self._record_learning_decision(
            trajectory,
            decision,
        )

        memory_recall_meta: Dict[str, Any] = {}
        provider_meta: Dict[str, Any] = {}
        if decision.memory_recall_required:
            memory_recall_meta = await self._consume_resolved_memory(request, decision)
            trajectory.memory_recall_count = memory_recall_meta.get("memory_recall_count")
            trajectory.memory_recall_refs = [
                item.get("id", "")
                for item in (memory_recall_meta.get("memory_context") or {}).get("recall", [])[:5]
                if item.get("id")
            ]
            await self._record_proactive_continuity_decision(
                trajectory,
                decision,
                memory_recall_meta,
            )

        try:
            if decision.topology.value == "reasoning":
                text, provider_meta = await self._run_reasoning(request, decision, plan, meter)
            elif decision.is_graph_required:
                text, provider_meta = await self._run_graph(request, decision, plan, meter)
            else:
                text, provider_meta = await self._run_simple(request, decision, plan, meter)
        except Exception as exc:
            error_type = type(exc).__name__
            logger.error(
                "ChatRuntime.execute failed; attempting canonical fallback",
                extra={"correlation_id": ctx.correlation_id, "error_type": error_type},
            )
            self._emitter.emit(
                RuntimeEventType.REQUEST_FAILED,
                error_type=error_type,
                status="error",
                metadata={"error_code": "CHAT_EXECUTION_FAILED"},
            )
            conversation_id = ctx.require_conversation_id()
            fallback = await build_runtime_fallback(
                runtime=self,
                request=request,
                failure=exc,
                correlation_id=ctx.correlation_id,
                conversation_id=conversation_id,
                start_time=start,
                decision=decision,
            )
            if fallback is not None and fallback.answer:
                if decision.memory_write_allowed:
                    await self._persist_memory(
                        request,
                        fallback.answer,
                        memory_recall_meta,
                        plan,
                    )
                await self._record_trajectory_completion(
                    trajectory,
                    decision,
                    fallback.answer,
                    start,
                    meter,
                    provider_meta or {},
                    memory_recall_meta,
                    error=f"fallback:{error_type}",
                )
                await self._record_execution_outcome(
                    trajectory.trajectory_id,
                    decision,
                    decision_observation_id,
                    fallback.answer,
                    start,
                    meter,
                    memory_recall_meta,
                    success=False,
                    provider_meta=provider_meta or {},
                )
                return fallback
            await self._record_trajectory_completion(
                trajectory,
                decision,
                "",
                start,
                meter,
                {},
                memory_recall_meta,
                error="all_execution_paths_failed",
            )
            await self._record_execution_outcome(
                trajectory.trajectory_id,
                decision,
                decision_observation_id,
                "",
                start,
                meter,
                memory_recall_meta,
                success=False,
                provider_meta={},
            )
            return ChatExecutionResult(
                answer="",
                status=ChatExecutionStatus.ERROR,
                metadata=ChatRuntimeMetadata(
                    correlation_id=ctx.correlation_id,
                    latency_ms=(time.time() - start) * 1000.0,
                    mode="emergency",
                    degraded_mode=True,
                    degradation_reason=f"all_execution_paths_failed:{error_type}",
                ),
            )

        if decision.memory_write_allowed:
            await self._persist_memory(request, text, memory_recall_meta, plan)

        latency_ms = (time.time() - start) * 1000.0
        await self._record_trajectory_completion(
            trajectory,
            decision,
            text,
            start,
            meter,
            provider_meta,
            memory_recall_meta,
        )
        await self._record_execution_outcome(
            trajectory.trajectory_id,
            decision,
            decision_observation_id,
            text,
            start,
            meter,
            memory_recall_meta,
            success=True,
            provider_meta=provider_meta,
        )

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

        result = self._build_result(
            request,
            decision,
            provider_meta,
            start,
            memory_recall_meta,
            text,
            latency_ms,
        )
        result.metadata.extra["trajectory_id"] = trajectory.trajectory_id
        result.metadata.extra["capability_receipt"] = self._build_capability_receipt(
            decision,
            plan,
        )
        return result

    async def execute_stream(
        self, request: ChatExecutionRequest
    ) -> AsyncIterator[ChatStreamChunk]:
        ctx = request.context
        sequence = 0
        request_id = ctx.request_id or str(uuid.uuid4())
        response_id = ctx.request_id or str(uuid.uuid4())
        conversation_id = ctx.require_conversation_id()

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
            return

        decision = await self._decide(request)
        await self._record_user_behavior_observation(request, decision)
        plan = self._build_authorized_plan(request, decision)
        approval_gate = await self._resolve_human_approval_gate(request, decision)
        if approval_gate is not None:
            approval_metadata = {
                "approval_id": approval_gate.approval_id,
                "approval_status": approval_gate.status,
                "intent": approval_gate.intent,
                "risk_level": approval_gate.risk_level,
                "reason_codes": list(approval_gate.reason_codes),
                "expires_at": approval_gate.expires_at,
                "mode": approval_gate.mode,
            }
            yield self._enrich_chunk(
                ChatStreamChunk(
                    type=ChatStreamEventType.APPROVAL,
                    content=approval_gate.message,
                    correlation_id=ctx.correlation_id,
                    metadata=approval_metadata,
                ),
                sequence,
                request_id,
                response_id,
                conversation_id,
            )
            sequence += 1
            yield self._enrich_chunk(
                ChatStreamChunk(
                    type=ChatStreamEventType.COMPLETE,
                    content="",
                    correlation_id=ctx.correlation_id,
                    metadata={
                        **approval_metadata,
                        "status": "gate",
                    },
                ),
                sequence,
                request_id,
                response_id,
                conversation_id,
            )
            return
        meter = ExecutionBudgetMeter(plan.budget)
        meter.start()
        trajectory = self._trajectory_recorder.start()
        decision_observation_id = await self._record_learning_decision(
            trajectory,
            decision,
        )
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
            memory_recall_meta = await self._consume_resolved_memory(request, decision)
            trajectory.memory_recall_count = memory_recall_meta.get("memory_recall_count")
            trajectory.memory_recall_refs = [
                item.get("id", "")
                for item in (memory_recall_meta.get("memory_context") or {}).get("recall", [])[:5]
                if item.get("id")
            ]
            await self._record_proactive_continuity_decision(
                trajectory,
                decision,
                memory_recall_meta,
            )

        streamed_text = ""
        provider_meta: Dict[str, Any] = {}
        generation_error: Optional[Exception] = None
        recovered_error_type: Optional[str] = None

        gen = (
            self._run_reasoning_stream(
                request,
                decision,
                plan,
                meter,
                _meta=provider_meta,
            )
            if decision.topology.value == "reasoning"
            else (
                self._run_graph_stream(
                    request,
                    decision,
                    plan,
                    meter,
                    _meta=provider_meta,
                )
                if decision.is_graph_required
                else self._run_simple_stream(
                    request,
                    decision,
                    plan,
                    meter,
                    memory_recall_meta,
                    _meta=provider_meta,
                )
            )
        )

        try:
            async for chunk in gen:
                if chunk.type == "content":
                    streamed_text += chunk.content
                if chunk.type == ChatStreamEventType.COMPLETE:
                    continue
                yield self._enrich_chunk(
                    chunk,
                    sequence,
                    request_id,
                    response_id,
                    conversation_id,
                )
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
            recovered_error_type = type(exc).__name__
            logger.error(
                "ChatRuntime stream execution failed; attempting canonical fallback",
                extra={
                    "correlation_id": ctx.correlation_id,
                    "error_type": recovered_error_type,
                },
            )
            self._emitter.emit(
                RuntimeEventType.REQUEST_FAILED,
                error_type=recovered_error_type,
                status="error",
                metadata={"error_code": "CHAT_STREAM_EXECUTION_FAILED"},
            )

            fallback: Optional[ChatExecutionResult] = None
            try:
                fallback = await build_runtime_fallback(
                    runtime=self,
                    request=request,
                    failure=exc,
                    correlation_id=ctx.correlation_id,
                    conversation_id=conversation_id,
                    start_time=stream_start,
                    decision=decision,
                )
            except Exception as fallback_exc:
                logger.error(
                    "ChatRuntime stream fallback failed",
                    extra={
                        "correlation_id": ctx.correlation_id,
                        "error_type": type(fallback_exc).__name__,
                    },
                )
                self._emitter.emit(
                    RuntimeEventType.REQUEST_FAILED,
                    error_type=type(fallback_exc).__name__,
                    status="fallback_error",
                    metadata={"error_code": "CHAT_STREAM_FALLBACK_FAILED"},
                )

            if fallback is not None and fallback.answer:
                fallback_meta = fallback.metadata.to_dict()
                for key in _CANONICAL_META_KEYS:
                    value = fallback_meta.get(key)
                    if value is not None:
                        provider_meta[key] = value
                provider_meta["fallback_level"] = max(
                    1,
                    int(provider_meta.get("fallback_level", 0) or 0),
                )
                provider_meta["used_fallback"] = True
                provider_meta["degraded_mode"] = True
                provider_meta["fallback_reason"] = (
                    provider_meta.get("fallback_reason")
                    or "stream_primary_execution_failed"
                )
                provider_meta["degradation_reason"] = (
                    provider_meta.get("degradation_reason")
                    or "stream_primary_execution_failed"
                )
                streamed_text += fallback.answer
                yield self._enrich_chunk(
                    ChatStreamChunk(
                        type="content",
                        content=fallback.answer,
                        correlation_id=ctx.correlation_id,
                        metadata={
                            "response_source": provider_meta.get("response_source"),
                            "actual_provider": provider_meta.get("actual_provider"),
                            "actual_model": provider_meta.get("actual_model"),
                            "fallback_level": provider_meta.get("fallback_level", 1),
                            "degraded_mode": True,
                        },
                    ),
                    sequence,
                    request_id,
                    response_id,
                    conversation_id,
                )
                sequence += 1
            else:
                generation_error = exc
                provider_meta["generation_error"] = True
                provider_meta["degraded_mode"] = True
                provider_meta["degradation_reason"] = "all_execution_paths_failed"
                yield self._enrich_chunk(
                    ChatStreamChunk(
                        type="error",
                        content="Unable to complete the response.",
                        correlation_id=ctx.correlation_id,
                        metadata={
                            "error_code": "CHAT_GENERATION_FAILED",
                            "error_type": type(exc).__name__,
                            "correlation_id": ctx.correlation_id,
                            "requested_provider": request.preferred_provider,
                            "requested_model": request.preferred_model,
                            "actual_provider": provider_meta.get("actual_provider"),
                            "actual_model": provider_meta.get("actual_model"),
                            "runtime_engine": provider_meta.get("runtime_engine"),
                            "fallback_level": provider_meta.get("fallback_level", 0),
                            "degradation_reason": "all_execution_paths_failed",
                        },
                    ),
                    sequence,
                    request_id,
                    response_id,
                    conversation_id,
                )
                sequence += 1

        memory_persistence_failed = False
        if decision.memory_write_allowed and streamed_text:
            await self._persist_memory(
                request,
                streamed_text,
                memory_recall_meta,
                plan,
            )
            memory_persistence_failed = (
                memory_recall_meta.get("memory_persistence_status") == "failed"
            )

        transcript_result = TranscriptPersistenceResult(
            status="skipped",
            conversation_id=conversation_id,
            reason="generation_incomplete",
        )
        if streamed_text and generation_error is None:
            transcript_result = await self._persist_transcript(
                request,
                streamed_text,
                provider_meta,
                trajectory_id=trajectory.trajectory_id,
            )
        transcript_meta = transcript_result.to_metadata()
        transcript_persistence_failed = transcript_result.status in {
            "failed",
            "rejected",
        }

        latency_ms = (time.time() - stream_start) * 1000.0
        success = bool(streamed_text) and generation_error is None
        await self._record_trajectory_completion(
            trajectory,
            decision,
            streamed_text,
            stream_start,
            meter,
            provider_meta,
            memory_recall_meta,
            error=(
                f"fallback:{recovered_error_type}"
                if recovered_error_type and generation_error is None
                else type(generation_error).__name__
                if generation_error
                else None
            ),
        )
        await self._record_execution_outcome(
            trajectory.trajectory_id,
            decision,
            decision_observation_id,
            streamed_text,
            stream_start,
            meter,
            memory_recall_meta,
            success=success,
            transcript_meta=transcript_meta,
            provider_meta=provider_meta,
        )

        terminal_metadata = self._build_stream_terminal_metadata(
            request,
            decision,
            provider_meta,
            memory_recall_meta,
            transcript_meta,
            latency_ms,
            request_id,
            response_id,
            generation_error=generation_error,
            memory_persistence_failed=memory_persistence_failed,
            transcript_persistence_failed=transcript_persistence_failed,
        )
        terminal_metadata["trajectory_id"] = trajectory.trajectory_id
        terminal_metadata["capability_receipt"] = self._build_capability_receipt(
            decision,
            plan,
        )
        terminal_metadata["proactive_continuity"] = dict(
            memory_recall_meta.get("proactive_continuity") or {"candidates": []}
        )
        terminal_metadata["continuity_primary_candidate_id"] = (
            memory_recall_meta.get("continuity_primary_candidate_id")
        )
        terminal_metadata["continuity_ambiguous"] = bool(
            memory_recall_meta.get("continuity_ambiguous", False)
        )
        terminal_metadata["continuity_agenda_reason_codes"] = list(
            memory_recall_meta.get("continuity_agenda_reason_codes") or []
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
            degraded_mode=(
                provider_meta.get("degraded_mode", False)
                or memory_persistence_failed
                or transcript_persistence_failed
            ),
            memory_recall_count=memory_recall_meta.get("memory_recall_count", 0),
            metadata={
                "memory_persistence_status": memory_recall_meta.get(
                    "memory_persistence_status",
                    "skipped",
                ),
                **transcript_meta,
            },
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

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_transcript(
        self,
        request: ChatExecutionRequest,
        response_text: str,
        provider_meta: Dict[str, Any],
        *,
        trajectory_id: str | None = None,
    ) -> TranscriptPersistenceResult:
        """Persist one completed turn through the canonical transcript owner."""
        ctx = request.context
        conversation_id = ctx.require_conversation_id()

        try:
            uuid.UUID(str(ctx.tenant_id))
            uuid.UUID(str(ctx.user_id))
            uuid.UUID(str(conversation_id))
        except (TypeError, ValueError, AttributeError):
            result = TranscriptPersistenceResult(
                status="rejected",
                conversation_id=conversation_id,
                reason="transcript_identity_not_uuid",
                error_type="ValueError",
            )
            self._emitter.emit(
                RuntimeEventType.PERSISTENCE_FAILED,
                error_type="ValueError",
                metadata={
                    "target": "transcript",
                    "error_code": "TRANSCRIPT_IDENTITY_INVALID",
                    "request_id": ctx.request_id,
                    "correlation_id": ctx.correlation_id,
                    "user_id": ctx.user_id,
                    "tenant_id": ctx.tenant_id,
                    "session_id": ctx.session_id,
                    "conversation_id": conversation_id,
                },
            )
            return result

        gateway = self._conversation_gateway or get_conversation_runtime_gateway()
        result = await gateway.persist_completed_turn(
            ctx,
            user_text=self._extract_user_message(request.messages),
            assistant_text=response_text,
            response_metadata={
                **{
                    key: value
                    for key, value in provider_meta.items()
                    if key in _CANONICAL_META_KEYS or key in _RICH_RESULT_KEYS
                },
                **({"trajectory_id": trajectory_id} if trajectory_id else {}),
            },
        )

        event_type = (
            RuntimeEventType.PERSISTENCE_COMPLETED
            if result.success
            else RuntimeEventType.PERSISTENCE_FAILED
        )
        self._emitter.emit(
            event_type,
            error_type=result.error_type,
            metadata={
                "target": "transcript",
                "status": result.status,
                "reason": result.reason,
                "persisted_count": result.persisted_messages,
                "request_id": ctx.request_id,
                "correlation_id": ctx.correlation_id,
                "user_id": ctx.user_id,
                "tenant_id": ctx.tenant_id,
                "session_id": ctx.session_id,
                "conversation_id": result.conversation_id,
                "user_message_id": result.user_message_id,
                "assistant_message_id": result.assistant_message_id,
            },
        )
        return result

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    async def _consume_resolved_memory(
        self, request: ChatExecutionRequest, decision: ExecutionDecision
    ) -> Dict[str, Any]:
        """Adapt already-resolved typed memory evidence for legacy consumers.

        This method performs no retrieval. RuntimeEvidenceResolver has already
        called MemoryRuntimeManager -> NeuroRecall before CORTEX Stage 2. The
        temporary ``request.metadata.memory_context`` view is derived only from
        ``decision.cognitive_context.evidence`` so there is still one context truth.
        """
        meta: Dict[str, Any] = {
            "memory_recall_status": "skipped",
            "memory_recall_count": 0,
            "memory_latency_ms": 0.0,
            "memory_persistence_status": "skipped",
            "memory_degraded": False,
            "memory_degradation_reason": None,
        }
        cognitive_context = decision.cognitive_context
        if cognitive_context is None:
            meta.update(
                {
                    "memory_recall_status": "unavailable",
                    "memory_degraded": True,
                    "memory_degradation_reason": "resolved_cognitive_context_missing",
                }
            )
            return meta

        memory_evidence = [
            item
            for item in cognitive_context.evidence
            if getattr(item.source, "value", str(item.source)) == "memory"
        ]
        continuity_evidence = [
            item
            for item in cognitive_context.evidence
            if getattr(item.source, "value", str(item.source)) == "user_model"
        ]

        recall_items: List[Dict[str, Any]] = []
        for item in memory_evidence[: decision.memory_top_k]:
            observed_at = item.temporal.observed_at
            timestamp: Any = None
            if observed_at is not None:
                timestamp = observed_at.timestamp()
            recall_items.append(
                {
                    "id": item.evidence_id,
                    "content": item.content,
                    "timestamp": timestamp,
                    "relevance": item.relevance,
                    "confidence": item.confidence,
                    "source_ref": item.source_ref,
                }
            )

        continuity_items: List[Dict[str, Any]] = []
        for item in continuity_evidence[:5]:
            item_meta = dict(item.metadata or {})
            continuity_items.append(
                {
                    "id": item.evidence_id,
                    "subject": item.content,
                    "source_type": item_meta.get("source_type"),
                    "source_id": item_meta.get("source_id") or item.source_ref,
                    "utility": item_meta.get("utility", item.relevance),
                    "confidence": item.confidence,
                    "urgency": item_meta.get("urgency", "normal"),
                    "interruption_cost": item_meta.get("interruption_cost", 0.0),
                    "reason_codes": list(item_meta.get("reason_codes") or []),
                    "resume_primary": bool(item_meta.get("resume_primary", False)),
                    "resume_ambiguous": bool(item_meta.get("resume_ambiguous", False)),
                    "execution_authorized": False,
                }
            )

        context_meta = cognitive_context.metadata
        meta.update(
            {
                "memory_recall_status": context_meta.get(
                    "memory_recall_status",
                    "success",
                ),
                "memory_recall_count": len(memory_evidence),
                "memory_latency_ms": float(
                    context_meta.get("memory_latency_ms") or 0.0
                ),
                "memory_degraded": bool(
                    context_meta.get("memory_degraded", False)
                ),
                "memory_degradation_reason": context_meta.get(
                    "memory_degradation_reason"
                ),
                "memory_retrieval_health": dict(
                    context_meta.get("memory_retrieval_health") or {}
                ),
                "memory_context": {"recall": recall_items},
                "proactive_continuity": {"candidates": continuity_items},
                "continuity_status": context_meta.get(
                    "continuity_status",
                    "success",
                ),
                "continuity_count": len(continuity_items),
                "continuity_candidate_ids": [
                    str(item.get("id") or "")
                    for item in continuity_items
                    if item.get("id")
                ],
                "continuity_source_types": [
                    str(item.get("source_type") or "")
                    for item in continuity_items
                    if item.get("source_type")
                ],
                "continuity_primary_candidate_id": context_meta.get(
                    "continuity_primary_candidate_id"
                ),
                "continuity_ambiguous": bool(
                    context_meta.get("continuity_ambiguous", False)
                ),
                "continuity_agenda_reason_codes": list(
                    context_meta.get("continuity_agenda_reason_codes") or []
                ),
            }
        )

        request.metadata["memory_context"] = {"recall": list(recall_items)}
        request.metadata["proactive_continuity"] = {
            "candidates": list(continuity_items),
            "primary_candidate_id": context_meta.get(
                "continuity_primary_candidate_id"
            ),
            "ambiguous": bool(
                context_meta.get("continuity_ambiguous", False)
            ),
            "reason_codes": list(
                context_meta.get("continuity_agenda_reason_codes") or []
            ),
        }
        return meta

    async def _persist_memory(
        self,
        request: ChatExecutionRequest,
        response_text: str,
        memory_recall_meta: Dict[str, Any],
        plan: AuthorizedExecutionPlan,
    ) -> Dict[str, Any]:
        if not await ActionExecutionGate.authorize(plan, "memory.write"):
            result = {
                "status": "rejected",
                "reason": "memory_write_not_authorized",
                "persisted": 0,
            }
            memory_recall_meta["memory_persistence_status"] = "denied_by_policy"
            return result

        ctx = request.context
        user_message = self._extract_user_message(request.messages)
        if not user_message.strip():
            result = {
                "status": "noop",
                "reason": "empty_user_interaction",
                "persisted": 0,
            }
            memory_recall_meta["memory_persistence_status"] = "no_candidate"
            return result

        policy_context = {
            "memory_write_authorized": True,
            "allowed_capabilities": list(plan.allowed_capabilities),
            "policy_decision_id": plan.policy_decision_id,
            "execution_id": plan.execution_id,
            "authorized_user_id": plan.authorized_user_id,
            "authorized_tenant_id": plan.authorized_tenant_id,
            "authorized_session_id": plan.authorized_session_id,
        }

        try:
            from ai_karen_engine.core.memory import get_memory_manager

            mem = get_memory_manager()
            result = await mem.process_interaction(
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
                request_id=ctx.request_id,
                correlation_id=ctx.correlation_id,
                actor_id=ctx.user_id,
                session_id=ctx.session_id,
                conversation_id=ctx.conversation_id,
                policy_context=policy_context,
            )

            persisted = int(result.get("persisted") or 0)
            admitted = int(result.get("admitted") or 0)
            formation_status = str(result.get("status") or "unknown")
            reason = result.get("reason")

            if formation_status == "rejected" and reason == "memory_write_not_authorized":
                memory_recall_meta["memory_persistence_status"] = "failed"
                memory_recall_meta["memory_degraded"] = True
                memory_recall_meta["memory_degradation_reason"] = (
                    "memory_authorization_proof_rejected"
                )
            elif persisted > 0:
                memory_recall_meta["memory_persistence_status"] = "persisted"
            elif formation_status in {"failed", "error"}:
                memory_recall_meta["memory_persistence_status"] = "failed"
                memory_recall_meta["memory_degraded"] = True
                memory_recall_meta["memory_degradation_reason"] = (
                    "memory_persistence_failed"
                )
            else:
                memory_recall_meta["memory_persistence_status"] = "no_candidate"

            memory_recall_meta["memory_candidate_count"] = int(
                result.get("extracted") or 0
            )
            memory_recall_meta["memory_admitted_count"] = admitted
            memory_recall_meta["memory_persisted_count"] = persisted
            memory_recall_meta["memory_formation_status"] = formation_status
            if reason:
                memory_recall_meta["memory_formation_reason"] = str(reason)

            event_type = (
                RuntimeEventType.PERSISTENCE_FAILED
                if memory_recall_meta["memory_persistence_status"] == "failed"
                else RuntimeEventType.PERSISTENCE_COMPLETED
            )
            self._emitter.emit(
                event_type,
                policy_decision_id=plan.policy_decision_id,
                metadata={
                    "target": "memory",
                    "formation_status": formation_status,
                    "reason": reason,
                    "candidate_count": memory_recall_meta["memory_candidate_count"],
                    "admitted_count": admitted,
                    "persisted_count": persisted,
                    "request_id": ctx.request_id,
                    "correlation_id": ctx.correlation_id,
                    "user_id": ctx.user_id,
                    "tenant_id": ctx.tenant_id,
                    "session_id": ctx.session_id,
                    "conversation_id": ctx.conversation_id,
                },
            )
            return result

        except Exception as exc:
            error_type = type(exc).__name__
            logger.warning(
                "Memory persistence failed",
                extra={
                    "correlation_id": ctx.correlation_id,
                    "error_type": error_type,
                },
            )
            memory_recall_meta["memory_persistence_status"] = "failed"
            memory_recall_meta["memory_degraded"] = True
            memory_recall_meta["memory_degradation_reason"] = (
                "memory_persistence_failed"
            )
            self._emitter.emit(
                RuntimeEventType.PERSISTENCE_FAILED,
                error_type=error_type,
                metadata={"target": "memory", "error_code": "MEMORY_PERSISTENCE_FAILED"},
            )
            return {
                "status": "failed",
                "reason": "memory_persistence_failed",
                "persisted": 0,
                "error_type": error_type,
            }

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    async def _decide(self, request: ChatExecutionRequest) -> ExecutionDecision:
        return await self._composition.cortex.decide(request)

    async def _record_user_behavior_observation(
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
    ) -> None:
        """Persist privacy-safe evidence of an explicit user request.

        This observes user behavior only. Provider/model outcomes, fallbacks,
        latency, and execution success belong to trajectory/outcome learning.
        """
        runtime = getattr(self._composition, "user_model_runtime", None)
        intent = str(decision.intent or "").strip().casefold()
        if (
            runtime is None
            or not decision.memory_write_allowed
            or intent in {"", "unknown", "general_assist", "fallback"}
        ):
            return

        ctx = request.context
        domain = self._safe_behavior_dimension(request.metadata.get("domain"))
        task_type = self._safe_behavior_dimension(request.metadata.get("task_type"))
        signature_source = "|".join(
            (
                "chat",
                f"intent={intent}",
                f"domain={domain or 'none'}",
                f"task_type={task_type or 'none'}",
            )
        )
        context_signature = (
            "chat:" + hashlib.sha256(signature_source.encode("utf-8")).hexdigest()[:20]
        )
        confidence = max(
            0.0,
            min(1.0, float(decision.intent_confidence or 0.65)),
        )

        try:
            from ai_karen_engine.core.personalization.behavior.contracts import (
                BehaviorObservation,
            )

            await runtime.ingest_behavior_observation(
                BehaviorObservation(
                    observation_id=str(ctx.request_id or ctx.correlation_id),
                    pattern_id="",
                    user_id=str(ctx.user_id),
                    tenant_id=str(ctx.tenant_id),
                    context_signature=context_signature,
                    action=intent,
                    outcome="user_requested",
                    observed_at=datetime.datetime.utcnow(),
                    metadata={
                        "confidence": confidence,
                        "source": "chat.user_request",
                        "domain": domain,
                        "task_type": task_type,
                        "explicit_user_action": True,
                    },
                )
            )
            self._emitter.emit(
                RuntimeEventType.PERSISTENCE_COMPLETED,
                status="stored",
                metadata={
                    "target": "personalization_behavior",
                    "intent": intent,
                },
            )
        except Exception as exc:
            logger.warning(
                "personalization.behavior_observation_failed",
                extra={
                    "correlation_id": ctx.correlation_id,
                    "error_type": type(exc).__name__,
                    "intent": intent,
                },
            )
            self._emitter.emit(
                RuntimeEventType.PERSISTENCE_FAILED,
                error_type=type(exc).__name__,
                metadata={
                    "target": "personalization_behavior",
                    "error_code": "BEHAVIOR_OBSERVATION_PERSISTENCE_FAILED",
                },
            )

    @staticmethod
    def _safe_behavior_dimension(value: Any) -> str | None:
        raw = str(value or "").strip().casefold()
        if not raw or len(raw) > 64:
            return None
        if any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in raw):
            return None
        return raw

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
            max_model_calls=decision.max_model_calls,
            max_tool_calls=len(decision.tool_requirements) + 5,
            max_reasoning_steps=decision.max_steps,
            max_output_tokens=request.max_tokens or 4096,
        )
        degradation = DegradationState(
            degraded=decision.execution_mode.value == "degraded",
            reason_code=(
                decision.policy_reason_codes[0]
                if decision.policy_reason_codes
                else None
            ),
            level=(
                decision.risk_level.value
                if hasattr(decision.risk_level, "value")
                else str(decision.risk_level)
            ),
        )
        allowed_caps = list(decision.required_capabilities)
        if decision.memory_write_allowed and "memory.write" not in allowed_caps:
            allowed_caps.append("memory.write")

        policy_constraints = decision.policy_constraints or {}
        allowed_tools = (
            list(policy_constraints.get("allowed_tools") or [])
            if "allowed_tools" in policy_constraints
            else list(decision.tool_requirements)
        )
        allowed_plugins = (
            list(policy_constraints.get("allowed_plugins") or [])
            if "allowed_plugins" in policy_constraints
            else list(decision.plugin_candidates)
        )
        allowed_agents = list(policy_constraints.get("allowed_agents") or [])

        return AuthorizedExecutionPlan(
            execution_id=f"exec-{ctx.request_id}",
            policy_decision_id=(
                decision.policy_decision_id or f"policy-{ctx.correlation_id}"
            ),
            authorized_user_id=ctx.user_id,
            authorized_tenant_id=ctx.tenant_id,
            authorized_session_id=ctx.session_id,
            topology=decision.topology,
            allowed_capabilities=allowed_caps,
            allowed_tools=allowed_tools,
            allowed_plugins=allowed_plugins,
            allowed_agents=allowed_agents,
            budget=budget,
            memory_scope=decision.memory_scope,
            reasoning_modes=list(decision.reasoning_modes),
            workflow_id=decision.workflow_id,
            degraded_allowed=True,
            degradation_state=degradation,
            audit_context={
                "intent": decision.intent,
                "risk_level": (
                    decision.risk_level.value
                    if hasattr(decision.risk_level, "value")
                    else str(decision.risk_level)
                ),
                "reason_codes": decision.reason_codes,
                "reasoning_modes": list(decision.reasoning_modes),
                "max_model_calls": decision.max_model_calls,
                "allowed_agents": allowed_agents,
            },
        )

    async def _run_simple(
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        plan: AuthorizedExecutionPlan,
        meter: ExecutionBudgetMeter,
        memory_recall_meta: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Simple conversational path: CORTEX -> ExpressionGateway."""
        if not await meter.consume_model_call():
            raise RuntimeError("Execution budget exhausted: max_model_calls")

        ctx = request.context
        gateway = self._composition.expression_gateway
        prompt_messages, prompt_telemetry = await self._assemble_prompt_with_telemetry(
            request,
            decision,
            memory_recall_meta,
        )
        task = ExpressionTask(
            task_id=f"expr_{ctx.correlation_id}",
            kind="chat",
            messages=prompt_messages,
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
                "memory_context": (
                    memory_recall_meta.get("memory_context", {})
                    if hasattr(memory_recall_meta, "get")
                    else {}
                ),
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
            degradation_reason=(
                result.degradation_reason if result.degraded else None
            ),
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
            "fallback_reason": (
                (result.metadata or {}).get("degradation_reason")
                if result.degraded
                else None
            ),
            "degraded_mode": result.degraded,
            "degradation_reason": result.degradation_reason,
            "degradation_type": (result.metadata or {}).get("degradation_type"),
            "provider_attempts": getattr(result, "attempts", []) or [],
            "usage": dict((result.metadata or {}).get("usage") or {}),
            "prompt_telemetry": prompt_telemetry,
            "execution_spans": [
                {
                    "name": "prompt_assembly",
                    "duration_ms": prompt_telemetry.get("assembly_duration_ms", 0.0),
                    "source": "runtime_observed",
                },
                {
                    "name": "provider_generation",
                    "duration_ms": result.latency_ms,
                    "source": "expression_gateway",
                },
            ],
            "provenance": provenance,
        }
        normalized["consumer_insights"] = build_consumer_insights(
            prompt_telemetry=prompt_telemetry,
            provider_usage=normalized["usage"],
            execution_spans=normalized["execution_spans"],
            total_latency_ms=result.latency_ms
            + float(prompt_telemetry.get("assembly_duration_ms") or 0.0),
        )
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
        text, normalized = await self._run_simple(
            request,
            decision,
            plan,
            meter,
            memory_recall_meta,
        )
        if _meta is not None:
            _meta.update(normalized)
        yield ChatStreamChunk(
            type="content",
            content=text,
            correlation_id=request.context.correlation_id,
            metadata={
                "execution_mode": "direct",
                "actual_provider": normalized.get("actual_provider"),
                "actual_model": normalized.get("actual_model"),
                "response_source": normalized.get("response_source"),
                "topology": plan.topology.value,
            },
        )

    async def _run_graph(
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        plan: AuthorizedExecutionPlan,
        meter: ExecutionBudgetMeter,
    ) -> Tuple[str, Dict[str, Any]]:
        """Graph-required path: routed exclusively through WorkflowRuntime."""
        text, response_metadata = await get_workflow_runtime().run(
            request,
            decision,
            plan,
        )
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
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        plan: AuthorizedExecutionPlan,
        meter: ExecutionBudgetMeter,
    ) -> Tuple[str, Dict[str, Any]]:
        """Reasoning topology path through Runtime activation and ReasoningExecutor."""
        from ai_karen_engine.core.reasoning.contracts import (
            ReasoningBudget,
            ReasoningEvidence,
            ReasoningRequest,
        )
        from ai_karen_engine.core.runtime.reasoning_bridge import (
            get_runtime_reasoning_bridge,
        )

        ctx = request.context
        memory_items = []
        if request.metadata:
            memory_items = (
                (request.metadata or {}).get("memory_context", {}).get("recall") or []
            )
        recall_items = memory_items[: decision.memory_top_k]
        continuity_items = (
            (request.metadata or {})
            .get("proactive_continuity", {})
            .get("candidates", [])
        )[:5]

        evidence = [
            ReasoningEvidence(
                evidence_id=str(item.get("id", f"mem-{idx}")),
                type="memory",
                source="memory_recall",
                source_ref=str(item.get("timestamp", "")),
                content=str(item.get("content", "")),
                relevance=float(item.get("relevance") or 0.5),
                confidence=float(item.get("confidence") or 0.5),
                tenant_id=ctx.tenant_id,
            )
            for idx, item in enumerate(recall_items[: decision.memory_top_k])
        ]
        evidence.extend(
            ReasoningEvidence(
                evidence_id=str(item.get("id", f"continuity-{idx}")),
                type="continuity",
                source="proactive_continuity",
                source_ref=str(item.get("source_id") or ""),
                content=str(item.get("subject") or ""),
                relevance=float(item.get("utility") or 0.5),
                confidence=float(item.get("confidence") or 0.5),
                tenant_id=ctx.tenant_id,
            )
            for idx, item in enumerate(continuity_items)
            if str(item.get("subject") or "").strip()
        )

        objective = self._extract_user_message(request.messages)
        activation = get_runtime_reasoning_bridge().activate(
            objective=objective,
            evidence=[item.content for item in evidence if item.content],
            decision=decision,
            plan=plan,
            preferred_provider=request.preferred_provider,
            preferred_model=request.preferred_model,
        )

        canonical_request = ReasoningRequest(
            request_id=ctx.request_id,
            correlation_id=ctx.correlation_id,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            conversation_id=ctx.conversation_id,
            objective=objective,
            reasoning_modes=list(activation.reasoning_modes),
            evidence=evidence,
            constraints={
                "reasoning_depth": decision.reasoning_depth,
                "tool_requirements": list(decision.tool_requirements),
                "plugin_candidates": list(decision.plugin_candidates),
            },
            policy_decision_id=decision.policy_decision_id or "",
            budget=ReasoningBudget(
                max_reasoning_steps=decision.max_steps,
                max_model_calls=plan.budget.max_model_calls,
                max_duration_ms=decision.time_budget_ms,
                max_output_tokens=plan.budget.max_output_tokens,
            ),
            metadata={
                "correlation_id": ctx.correlation_id,
                "request_id": ctx.request_id,
                **activation.request_metadata,
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

        reasoning_started = time.perf_counter()
        result = await activation.executor.execute(canonical_request, plan, context)
        reasoning_duration_ms = (time.perf_counter() - reasoning_started) * 1000.0

        consumed_model_calls = int(result.diagnostics.get("model_calls", 0) or 0)
        for _ in range(consumed_model_calls):
            if not await meter.consume_model_call():
                raise RuntimeError("Execution budget exhausted: max_model_calls")
        consumed_steps = int(result.diagnostics.get("steps", 0) or 0)
        for _ in range(consumed_steps):
            if not await meter.consume_reasoning_step():
                raise RuntimeError("Execution budget exhausted: max_reasoning_steps")
        if not await meter.check_duration():
            raise RuntimeError("Execution budget exhausted: max_duration_ms")

        text = result.summary or ""
        if not text and result.hypotheses:
            text = "; ".join(h.statement for h in result.hypotheses[:3])

        activation_meta = dict(activation.runtime_metadata)
        provider_meta = {
            "requested_provider": request.preferred_provider,
            "requested_model": request.preferred_model,
            "actual_provider": activation_meta.get(
                "soft_reasoning_provider",
                "reasoning_executor",
            ),
            "actual_model": activation_meta.get(
                "soft_reasoning_model",
                "canonical",
            ),
            "runtime_engine": activation_meta.get(
                "soft_reasoning_runtime_engine",
                "reasoning",
            ),
            "response_source": "reasoning",
            "fallback_level": 0,
            "degraded_mode": result.status
            in ("failed", "budget_exhausted", "abstained"),
            "degradation_reason": (
                result.diagnostics.get("error")
                if result.status == "failed"
                else None
            ),
            "reasoning_id": result.reasoning_id,
            "reasoning_status": result.status,
            "reasoning_modes": list(activation.reasoning_modes),
            "reasoning_model_calls": consumed_model_calls,
            "reasoning_steps": consumed_steps,
            "execution_spans": [
                {
                    "name": "reasoning_executor",
                    "duration_ms": reasoning_duration_ms,
                    "source": "reasoning_executor",
                }
            ],
            **activation_meta,
        }
        if "counterfactual" in activation.reasoning_modes and result.hypotheses:
            provider_meta["counterfactuals"] = {
                "available": True,
                "authority": "reasoning_executor",
                "reasoning_id": result.reasoning_id,
                "scenarios": [
                    {
                        "id": hypothesis.hypothesis_id,
                        "statement": hypothesis.statement,
                        "confidence": hypothesis.confidence,
                        "uncertainty": hypothesis.uncertainty,
                        "status": hypothesis.status,
                        "supporting_evidence_refs": list(
                            hypothesis.supporting_evidence_refs
                        ),
                        "contradicting_evidence_refs": list(
                            hypothesis.contradicting_evidence_refs
                        ),
                    }
                    for hypothesis in result.hypotheses[:6]
                ],
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
        text, normalized = await self._run_reasoning(
            request,
            decision,
            plan,
            meter,
        )
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
                "reasoning_modes": normalized.get("reasoning_modes", []),
                "topology": plan.topology.value,
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _assemble_prompt(
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        memory_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Backward-compatible prompt message projection."""
        messages, _ = await self._assemble_prompt_with_telemetry(
            request,
            decision,
            memory_context,
        )
        return messages

    async def _assemble_prompt_with_telemetry(
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        memory_context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Assemble prompt and preserve PromptRuntime-owned consumer telemetry."""
        from ai_karen_engine.core.runtime.prompt import (
            PromptAssemblyRequest,
            get_prompt_runtime_service,
        )

        recall_items = (
            (memory_context or {}).get("recall", []) if memory_context else []
        )
        continuity_items = (
            (request.metadata or {})
            .get("proactive_continuity", {})
            .get("candidates", [])
        )
        if not recall_items and decision.memory_recall_required:
            recall_items = (
                (request.metadata or {}).get("memory_context", {}).get("recall") or []
            )

        assembly_request = PromptAssemblyRequest(
            prompt_id="karen.chat.default",
            prompt_version="v1.0.0",
            memory_items=recall_items if decision.memory_recall_required else [],
            continuity_items=(
                list(continuity_items)
                if decision.memory_recall_required
                else []
            ),
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

        assembly_started = time.perf_counter()
        result = await get_prompt_runtime_service().assemble_prompt(assembly_request)
        prompt_telemetry = dict(
            (result.metadata or {}).get("consumer_token_telemetry") or {}
        )
        prompt_telemetry["assembly_duration_ms"] = (
            time.perf_counter() - assembly_started
        ) * 1000.0
        return result.messages, prompt_telemetry

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
        if latency_ms is None:
            latency_ms = (time.time() - start) * 1000.0

        md = self._build_metadata(
            request,
            decision,
            normalized,
            latency_ms,
            memory_meta,
        )

        status = ChatExecutionStatus.OK
        if md.degraded_mode:
            status = ChatExecutionStatus.DEGRADED
        if normalized.get("degradation_reason") and "all_execution_paths_failed" in str(
            normalized.get("degradation_reason")
        ):
            status = ChatExecutionStatus.ERROR

        return ChatExecutionResult(
            answer=text,
            status=status,
            metadata=md,
            structured_content=dict(normalized.get("structured_content") or {}),
            actions=list(normalized.get("actions") or []),
            citations=list(normalized.get("citations") or []),
            sources=list(normalized.get("sources") or []),
            attachments=list(normalized.get("attachments") or []),
            artifacts=list(normalized.get("artifacts") or []),
        )

    def _normalize_graph_meta(
        self,
        response_metadata: Dict[str, Any],
        request: ChatExecutionRequest,
    ) -> Dict[str, Any]:
        raw = response_metadata or {}
        llm = raw.get("llm_metadata") or {}
        normalized = {
            "requested_provider": llm.get("requested_provider")
            or request.preferred_provider,
            "requested_model": llm.get("requested_model")
            or request.preferred_model,
            "actual_provider": llm.get("actual_provider"),
            "actual_model": llm.get("actual_model"),
            "runtime_engine": llm.get("runtime_engine"),
            "response_source": llm.get("response_source"),
            "fallback_level": llm.get("fallback_level", 0),
            "degraded_mode": bool(llm.get("degraded_mode")),
            "degradation_reason": llm.get("degradation_reason"),
            "llm": raw.get("llm"),
        }
        for key in _RICH_RESULT_KEYS:
            value = raw.get(key)
            if value is not None:
                normalized[key] = value
        for key in (
            "agent_consensus",
            "counterfactuals",
            "execution_spans",
            "vector_health",
            "prompt_telemetry",
            "usage",
        ):
            value = raw.get(key)
            if value is not None:
                normalized[key] = value
        return normalized

    def _build_metadata(
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        normalized: Dict[str, Any],
        latency_ms: float,
        memory_meta: Optional[Dict[str, Any]] = None,
    ) -> ChatRuntimeMetadata:
        ctx = request.context
        conversation_id = ctx.require_conversation_id()
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
            md.extra.update(
                {k: v for k, v in memory_meta.items() if k not in md.extra}
            )

        if md.fallback_level and md.fallback_level > 0:
            md.used_fallback = True

        md.extra.update(
            {
                k: v
                for k, v in normalized.items()
                if k not in _CANONICAL_META_KEYS
            }
        )
        md.extra["consumer_insights"] = build_consumer_insights(
            prompt_telemetry=normalized.get("prompt_telemetry"),
            provider_usage=normalized.get("usage"),
            execution_spans=normalized.get("execution_spans"),
            total_latency_ms=latency_ms,
            vector_health=(
                normalized.get("vector_health")
                or (memory_meta or {}).get("memory_retrieval_health")
            ),
            counterfactuals=normalized.get("counterfactuals"),
            agent_consensus=normalized.get("agent_consensus"),
        )
        return md

    @staticmethod
    def _build_capability_receipt(
        decision: ExecutionDecision,
        plan: AuthorizedExecutionPlan,
    ) -> Dict[str, Any]:
        """Return request-scoped capability truth for user-facing inspection.

        This receipt is descriptive only. It mirrors the already-authorized
        execution plan and CORTEX decision so clients can explain what KAREN
        could use for this request without becoming a second policy authority.
        """
        topology = (
            decision.topology.value
            if hasattr(decision.topology, "value")
            else str(decision.topology)
        )
        return {
            "policy_decision_id": plan.policy_decision_id,
            "execution_topology": topology,
            "allowed_capabilities": list(plan.allowed_capabilities),
            "forbidden_capabilities": list(decision.forbidden_capabilities),
            "allowed_tools": list(plan.allowed_tools),
            "allowed_plugins": list(plan.allowed_plugins),
            "allowed_agents": list(plan.allowed_agents),
            "requires_human_gate": bool(decision.requires_human_gate),
            "requires_resumability": bool(decision.requires_resumability),
            "workflow_id": decision.workflow_id,
            "workflow_version": decision.workflow_version,
            "reasoning_modes": list(plan.reasoning_modes),
            "execution_budget": {
                "max_duration_ms": plan.budget.max_duration_ms,
                "max_model_calls": plan.budget.max_model_calls,
                "max_tool_calls": plan.budget.max_tool_calls,
                "max_reasoning_steps": plan.budget.max_reasoning_steps,
                "max_output_tokens": plan.budget.max_output_tokens,
            },
            "policy_reason_codes": list(decision.policy_reason_codes),
        }

    async def _resolve_human_approval_gate(
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
    ) -> Optional[ApprovalRequiredResponse]:
        """Enforce CORTEX/RuntimePolicy human gates before any execution."""
        approval_id = str(request.metadata.get("approval_id") or "").strip()
        if not decision.requires_human_gate and not approval_id:
            return None

        try:
            pending = await get_approval_service().authorize_or_request(
                request,
                decision,
            )
        except ApprovalError:
            logger.warning(
                "runtime.approval_receipt_rejected",
                extra={
                    "correlation_id": request.context.correlation_id,
                    "approval_id": approval_id or None,
                    "user_id": request.context.user_id,
                    "tenant_id": request.context.tenant_id,
                },
            )
            return ApprovalRequiredResponse(
                approval_id=approval_id,
                message="This approval can no longer authorize the request.",
                status="invalid",
                intent=decision.intent,
                risk_level=str(
                    getattr(decision.risk_level, "value", decision.risk_level)
                ),
                reason_codes=["approval_receipt_invalid"],
            )

        if pending is None:
            return None

        return ApprovalRequiredResponse(
            approval_id=str(pending["approval_id"]),
            status=str(pending["status"]),
            intent=str(pending["intent"]),
            risk_level=str(pending["risk_level"]),
            reason_codes=list(pending.get("reason_codes") or []),
            expires_at=(
                pending["expires_at"].isoformat()
                if pending.get("expires_at")
                else None
            ),
        )

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
        from ai_karen_engine.core.observability.context import (
            bind_observability_context,
        )

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

    def _accumulate_chunk_metadata(
        self,
        chunk: ChatStreamChunk,
        meta: Dict[str, Any],
    ) -> None:
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
        for key in _RICH_RESULT_KEYS:
            value = chunk_meta.get(key)
            if value is not None:
                meta[key] = value

    def _build_stream_terminal_metadata(
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        provider_meta: Dict[str, Any],
        memory_recall_meta: Dict[str, Any],
        transcript_meta: Dict[str, Any],
        latency_ms: float,
        request_id: str,
        response_id: str,
        generation_error: Optional[Exception] = None,
        memory_persistence_failed: bool = False,
        transcript_persistence_failed: bool = False,
    ) -> Dict[str, Any]:
        ctx = request.context
        conversation_id = ctx.require_conversation_id()
        degraded = (
            provider_meta.get("degraded_mode", False)
            or memory_persistence_failed
            or transcript_persistence_failed
        )
        degradation_reason = provider_meta.get("degradation_reason")
        if not degradation_reason and transcript_persistence_failed and not generation_error:
            degradation_reason = (
                transcript_meta.get("transcript_persistence_reason")
                or "transcript_persistence_failed"
            )
        if not degradation_reason and memory_persistence_failed and not generation_error:
            degradation_reason = "memory_persistence_failed"

        return {
            "correlation_id": ctx.correlation_id,
            "request_id": request_id,
            "response_id": response_id,
            "conversation_id": conversation_id,
            "assistant_message_id": transcript_meta.get("assistant_message_id"),
            "user_message_id": transcript_meta.get("user_message_id"),
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
            "memory_recall_count": memory_recall_meta.get(
                "memory_recall_count",
                0,
            ),
            "memory_recall_status": memory_recall_meta.get(
                "memory_recall_status",
                "skipped",
            ),
            "memory_persistence_status": memory_recall_meta.get(
                "memory_persistence_status",
                "skipped",
            ),
            "memory_context": dict(
                memory_recall_meta.get("memory_context") or {"recall": []}
            ),
            "memory_candidate_count": int(
                memory_recall_meta.get("memory_candidate_count") or 0
            ),
            "memory_admitted_count": int(
                memory_recall_meta.get("memory_admitted_count") or 0
            ),
            "memory_persisted_count": int(
                memory_recall_meta.get("memory_persisted_count") or 0
            ),
            "memory_formation_status": memory_recall_meta.get(
                "memory_formation_status",
                "skipped",
            ),
            "memory_formation_reason": memory_recall_meta.get(
                "memory_formation_reason"
            ),
            "consumer_insights": build_consumer_insights(
                prompt_telemetry=provider_meta.get("prompt_telemetry"),
                provider_usage=provider_meta.get("usage"),
                execution_spans=provider_meta.get("execution_spans"),
                total_latency_ms=latency_ms,
                vector_health=(
                    provider_meta.get("vector_health")
                    or memory_recall_meta.get("memory_retrieval_health")
                ),
                counterfactuals=provider_meta.get("counterfactuals"),
                agent_consensus=provider_meta.get("agent_consensus"),
            ),
            "intent": decision.intent,
            "intent_confidence": decision.intent_confidence,
            "transcript_persistence_status": transcript_meta.get(
                "transcript_persistence_status",
                "skipped",
            ),
            "transcript_persistence_reason": transcript_meta.get(
                "transcript_persistence_reason"
            ),
            "transcript_persisted_count": transcript_meta.get(
                "transcript_persisted_count",
                0,
            ),
            "status": (
                "error"
                if generation_error
                else "degraded"
                if degraded
                else "ok"
            ),
            **{
                key: provider_meta.get(key)
                for key in _RICH_RESULT_KEYS
                if provider_meta.get(key) is not None
            },
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

    async def _record_learning_decision(
        self,
        trajectory: Any,
        decision: ExecutionDecision,
    ) -> Optional[str]:
        """Persist immutable decision-time lineage without affecting execution."""

        try:
            trajectory.intent = decision.intent
            trajectory.cortex_decision = {
                "topology": decision.topology.value,
                "execution_mode": decision.execution_mode.value,
                "risk_level": (
                    decision.risk_level.value
                    if hasattr(decision.risk_level, "value")
                    else str(decision.risk_level)
                ),
                "reason_codes": list(decision.reason_codes),
                "reasoning_modes": list(decision.reasoning_modes),
                "max_model_calls": decision.max_model_calls,
            }
            trajectory.policy_decision_id = decision.policy_decision_id
            trajectory.policy_allowed_capabilities = list(
                decision.required_capabilities
            )
            trajectory.policy_denied_capabilities = list(
                decision.forbidden_capabilities
            )

            if not await self._trajectory_recorder.persist_async(trajectory):
                return None

            snapshot = self._trajectory_recorder.build_feature_snapshot(
                trajectory,
                feature_version=TOPOLOGY_FEATURES_V1,
                intent=decision.intent,
                intent_confidence=decision.intent_confidence,
                complexity=decision.reasoning_depth,
                capability_hints={
                    "tool_requirements": list(decision.tool_requirements),
                    "plugin_candidates": list(decision.plugin_candidates),
                    "requires_agent_delegation": (
                        decision.requires_agent_delegation
                    ),
                    "requires_parallel_execution": (
                        decision.requires_parallel_execution
                    ),
                    "requires_human_gate": decision.requires_human_gate,
                },
                topology_signals={
                    "graph_required": decision.graph_required,
                    "reasoning_modes": list(decision.reasoning_modes),
                    "requires_resumability": decision.requires_resumability,
                },
                risk_signals={
                    "risk_level": (
                        decision.risk_level.value
                        if hasattr(decision.risk_level, "value")
                        else str(decision.risk_level)
                    ),
                },
                runtime_capabilities={
                    "required": list(decision.required_capabilities),
                    "forbidden": list(decision.forbidden_capabilities),
                },
                metadata={
                    "policy_decision_id": decision.policy_decision_id,
                    "policy_version": decision.policy_version,
                    "reason_codes": list(decision.reason_codes),
                    "policy_reason_codes": list(
                        decision.policy_reason_codes
                    ),
                },
            )
            persisted_snapshot = (
                await self._trajectory_recorder.record_feature_snapshot_async(
                    trajectory,
                    feature_snapshot=snapshot,
                )
            )
            if persisted_snapshot is None:
                return None

            candidate_actions = tuple(item.value for item in ExecutionTopology)
            observation = self._trajectory_recorder.build_decision_observation(
                trajectory,
                feature_snapshot_id=snapshot.feature_snapshot_id,
                decision_type=DecisionType.EXECUTION_TOPOLOGY.value,
                candidate_actions=candidate_actions,
                eligible_actions=(decision.topology.value,),
                chosen_action=decision.topology.value,
                chosen_probability=None,
                action_probabilities={},
                decision_id=decision.policy_decision_id,
                ope_eligible=False,
                ope_ineligible_reason=(
                    OpeEligibilityReason.MISSING_PROPENSITY.value
                ),
                metadata={
                    "eligibility_scope": "authorized_choice_only",
                    "policy_decision_id": decision.policy_decision_id,
                },
            )
            persisted_observation = (
                await self._trajectory_recorder.record_decision_observation_async(
                    trajectory,
                    decision_observation=observation,
                )
            )
            if persisted_observation is None:
                return None
            await self._trajectory_recorder.persist_async(trajectory)
            return observation.decision_observation_id
        except Exception as exc:
            logger.warning(
                "learning decision lineage recording failed",
                extra={
                    "trajectory_id": getattr(
                        trajectory,
                        "trajectory_id",
                        None,
                    ),
                    "error_type": type(exc).__name__,
                },
            )
            self._emitter.emit(
                RuntimeEventType.LEARNING_RECORDING_FAILED,
                error_type=type(exc).__name__,
                metadata={
                    "kind": "decision_lineage",
                    "trajectory_id": getattr(
                        trajectory,
                        "trajectory_id",
                        None,
                    ),
                },
            )
            return None

    async def _record_proactive_continuity_decision(
        self,
        trajectory: Any,
        decision: ExecutionDecision,
        memory_meta: Dict[str, Any],
    ) -> Optional[str]:
        """Record the deterministic continuity ranking decision honestly.

        The current ranker emits utilities, not calibrated action propensities.
        Therefore the observation is durable for supervised/ranking learning but
        explicitly OPE-ineligible until a behavior policy can provide real
        probabilities.
        """
        candidates = list(
            (memory_meta.get("proactive_continuity") or {}).get("candidates") or []
        )
        candidate_ids = [
            str(item.get("id") or "").strip()
            for item in candidates
            if str(item.get("id") or "").strip()
        ]
        if not candidate_ids:
            return None

        abstain_action = "__abstain__"
        actions = tuple([*candidate_ids, abstain_action])
        primary_id = str(
            memory_meta.get("continuity_primary_candidate_id") or ""
        ).strip()
        ambiguous = bool(memory_meta.get("continuity_ambiguous", False))
        chosen_action = (
            primary_id
            if primary_id and primary_id in candidate_ids and not ambiguous
            else abstain_action
        )

        source_types = [
            str(item.get("source_type") or "unknown")
            for item in candidates
        ]
        utilities = [
            max(0.0, min(1.0, float(item.get("utility") or 0.0)))
            for item in candidates
        ]
        interruption_costs = [
            max(0.0, min(1.0, float(item.get("interruption_cost") or 0.0)))
            for item in candidates
        ]
        high_urgency_count = sum(
            1
            for item in candidates
            if str(item.get("urgency") or "").casefold() == "high"
        )

        try:
            snapshot = self._trajectory_recorder.build_feature_snapshot(
                trajectory,
                feature_version=PROACTIVE_CONTINUITY_FEATURES_V1,
                intent=decision.intent,
                intent_confidence=decision.intent_confidence,
                ambiguity=1.0 if ambiguous else 0.0,
                memory_relevance=max(utilities) if utilities else 0.0,
                capability_hints={
                    "candidate_count": len(candidate_ids),
                    "source_types": source_types,
                    "utilities": utilities,
                    "interruption_costs": interruption_costs,
                    "high_urgency_count": high_urgency_count,
                    "abstain_available": True,
                },
                metadata={
                    "candidate_ids": candidate_ids,
                    "primary_candidate_id": primary_id or None,
                    "agenda_reason_codes": list(
                        memory_meta.get("continuity_agenda_reason_codes") or []
                    ),
                    "deterministic_ranker": True,
                },
            )
            persisted_snapshot = (
                await self._trajectory_recorder.record_feature_snapshot_async(
                    trajectory,
                    feature_snapshot=snapshot,
                )
            )
            if persisted_snapshot is None:
                return None

            observation = self._trajectory_recorder.build_decision_observation(
                trajectory,
                feature_snapshot_id=persisted_snapshot.feature_snapshot_id,
                decision_type=DecisionType.PROACTIVE_CONTINUITY.value,
                behavior_policy_id=PROACTIVE_CONTINUITY_POLICY_ID,
                behavior_policy_version=PROACTIVE_CONTINUITY_POLICY_VERSION,
                candidate_actions=actions,
                eligible_actions=actions,
                chosen_action=chosen_action,
                chosen_probability=None,
                action_probabilities={},
                ope_eligible=False,
                ope_ineligible_reason=OpeEligibilityReason.MISSING_PROPENSITY.value,
                metadata={
                    "candidate_source_types": source_types,
                    "primary_candidate_id": primary_id or None,
                    "ambiguous": ambiguous,
                    "deterministic_ranker": True,
                },
            )
            persisted_observation = (
                await self._trajectory_recorder.record_decision_observation_async(
                    trajectory,
                    decision_observation=observation,
                )
            )
            if persisted_observation is None:
                return None

            memory_meta["continuity_decision_observation_id"] = (
                persisted_observation.decision_observation_id
            )
            await self._trajectory_recorder.persist_async(trajectory)
            return persisted_observation.decision_observation_id
        except Exception as exc:
            logger.warning(
                "proactive continuity learning lineage recording failed",
                extra={
                    "trajectory_id": getattr(trajectory, "trajectory_id", None),
                    "error_type": type(exc).__name__,
                },
            )
            self._emitter.emit(
                RuntimeEventType.LEARNING_RECORDING_FAILED,
                error_type=type(exc).__name__,
                metadata={
                    "kind": "proactive_continuity_decision_lineage",
                    "trajectory_id": getattr(trajectory, "trajectory_id", None),
                },
            )
            return None

    async def _record_trajectory_completion(
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
        trajectory.executed_topology = decision.topology.value
        trajectory.cortex_decision = {
            "topology": decision.topology.value,
            "execution_mode": decision.execution_mode.value,
            "risk_level": (
                decision.risk_level.value
                if hasattr(decision.risk_level, "value")
                else str(decision.risk_level)
            ),
            "reason_codes": decision.reason_codes,
            "reasoning_modes": list(decision.reasoning_modes),
            "max_model_calls": decision.max_model_calls,
        }
        trajectory.policy_decision_id = decision.policy_decision_id
        trajectory.policy_allowed_capabilities = list(
            decision.required_capabilities
        )
        trajectory.policy_denied_capabilities = list(
            decision.forbidden_capabilities
        )
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
        await self._trajectory_recorder.complete_async(
            trajectory,
            execution_status=trajectory.execution_status,
            error_code=error,
            response_source=provider_meta.get("response_source"),
        )

    async def _record_execution_outcome(
        self,
        trajectory_id: Optional[str],
        decision: ExecutionDecision,
        decision_observation_id: Optional[str],
        text: str,
        start: float,
        meter: ExecutionBudgetMeter,
        memory_meta: Dict[str, Any],
        success: bool,
        transcript_meta: Optional[Dict[str, Any]] = None,
        provider_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        from ai_karen_engine.core.runtime.outcome.contracts import ExecutionStatus

        latency_ms = (time.time() - start) * 1000.0
        memory_status = memory_meta.get("memory_persistence_status", "skipped")
        transcript_status = (transcript_meta or {}).get(
            "transcript_persistence_status",
            "skipped",
        )
        persistence_failure = (
            memory_status == "failed"
            or transcript_status in {"failed", "rejected"}
        )
        durable_write_proven = (
            memory_status == "persisted"
            or transcript_status in {"persisted", "already_persisted"}
        )
        persistence_success: Optional[bool]
        if persistence_failure:
            persistence_success = False
        elif durable_write_proven:
            persistence_success = True
        else:
            persistence_success = None
        await self._outcome_recorder.record_execution_outcome_async(
            trajectory_id=trajectory_id,
            decision_observation_id=decision_observation_id,
            status=(
                ExecutionStatus.SUCCESS if success else ExecutionStatus.FAILURE
            ),
            latency_ms=latency_ms,
            fallback_count=int((provider_meta or {}).get("fallback_level", 0) or 0),
            response_completed=bool(text),
            persistence_success=persistence_success,
            metadata={
                "topology": decision.topology.value,
                "model_calls": meter.model_calls,
                "tool_calls": meter.tool_calls,
                "reasoning_steps": meter.reasoning_steps,
                "memory_persistence_status": memory_status,
                "transcript_persistence_status": transcript_status,
                "transcript_persistence_reason": (transcript_meta or {}).get(
                    "transcript_persistence_reason"
                ),
                "transcript_persisted_count": (transcript_meta or {}).get(
                    "transcript_persisted_count",
                    0,
                ),
                "continuity_decision_observation_id": memory_meta.get(
                    "continuity_decision_observation_id"
                ),
                "continuity_candidate_ids": list(
                    memory_meta.get("continuity_candidate_ids") or []
                ),
                "continuity_source_types": list(
                    memory_meta.get("continuity_source_types") or []
                ),
                "continuity_count": int(
                    memory_meta.get("continuity_count") or 0
                ),
                "continuity_primary_candidate_id": memory_meta.get(
                    "continuity_primary_candidate_id"
                ),
                "continuity_ambiguous": bool(
                    memory_meta.get("continuity_ambiguous", False)
                ),
                "continuity_agenda_reason_codes": list(
                    memory_meta.get("continuity_agenda_reason_codes") or []
                ),
            },
        )


_chat_runtime: Optional[ChatRuntime] = None


def get_chat_runtime() -> ChatRuntime:
    """Return the singleton authoritative chat runtime."""
    global _chat_runtime
    if _chat_runtime is None:
        _chat_runtime = ChatRuntime(composition=get_runtime_composition())
    return _chat_runtime
