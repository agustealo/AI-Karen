import asyncio
import datetime
from contextlib import ExitStack
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from uuid import uuid4

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.policy.runtime_policy import (
    PolicyDecision, RuntimePolicyEnforcer,
)
from ai_karen_engine.core.runtime.ag_ui_event_projection import AGUIEventProjection
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatExecutionStatus,
    ChatExecutionResult,
    ChatRuntimeMetadata,
    PersonaExecutionSnapshot,
    ChatStreamChunk,
    ChatStreamEventType,
)
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    TranscriptHistoryResult,
    TranscriptPersistenceResult,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.persistence.repositories.chat_run_repository import ChatRunLease
from ai_karen_engine.core.runtime.trajectory.contracts import ExecutionTrajectory
from ai_karen_engine.core.runtime.trajectory.recorder import TrajectoryRecorder
from ai_karen_engine.core.runtime.trajectory.store import InMemoryTrajectoryStore
from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
    ApprovalRequiredResponse,
)
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionBudgetMeter,
    ExecutionTopology,
)

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_ID = "11111111-1111-1111-1111-111111111111"
CONVERSATION_ID = "22222222-2222-2222-2222-222222222222"
USER_MESSAGE_ID = "33333333-3333-3333-3333-333333333333"
ASSISTANT_MESSAGE_ID = "44444444-4444-4444-4444-444444444444"


class _TranscriptGateway:
    def __init__(
        self,
        result: Optional[TranscriptPersistenceResult] = None,
    ) -> None:
        self.result = result or TranscriptPersistenceResult(
            status="persisted",
            conversation_id=CONVERSATION_ID,
            user_message_id=USER_MESSAGE_ID,
            assistant_message_id=ASSISTANT_MESSAGE_ID,
            persisted_messages=2,
        )
        self.calls: list[dict[str, Any]] = []
        self.reconciliation_calls: list[dict[str, Any]] = []
        self.reconciliation_result = TranscriptPersistenceResult(
            status="not_found", conversation_id=CONVERSATION_ID,
        )

    async def reconcile_interrupted_turn(
        self,
        context: ChatExecutionContext,
        *,
        user_text: str,
        assistant_text: str,
        persona_scope_id: str | None = None,
        run_lease=None,
    ) -> TranscriptPersistenceResult:
        self.reconciliation_calls.append({
            "context": context,
            "user_text": user_text,
            "assistant_text": assistant_text,
            "persona_scope_id": persona_scope_id,
            "run_lease": run_lease,
        })
        return self.reconciliation_result

    async def load_history(
        self, context: ChatExecutionContext, *, limit: int,
        persona_scope_id: str | None = None,
    ) -> TranscriptHistoryResult:
        return TranscriptHistoryResult(
            status="empty", conversation_id=context.conversation_id or "",
        )

    async def persist_completed_turn(
        self,
        context: ChatExecutionContext,
        *,
        user_text: str,
        assistant_text: str,
        response_metadata: Optional[Dict[str, Any]] = None,
        persona_scope_id: str | None = None,
    ) -> TranscriptPersistenceResult:
        self.calls.append(
            {
                "context": context,
                "user_text": user_text,
                "assistant_text": assistant_text,
                "response_metadata": dict(response_metadata or {}),
                "persona_scope_id": persona_scope_id,
            }
        )
        return self.result


def _make_runtime(
    gateway: Optional[_TranscriptGateway] = None,
) -> tuple[ChatRuntime, _TranscriptGateway]:
    resolved_gateway = gateway or _TranscriptGateway()
    return (
        ChatRuntime(conversation_gateway=resolved_gateway),
        resolved_gateway,
    )


def _make_request() -> ChatExecutionRequest:
    ctx = ChatExecutionContext(
        user_id=USER_ID,
        tenant_id=TENANT_ID,
        session_id="session-1",
        conversation_id=CONVERSATION_ID,
        request_id="req-1",
        correlation_id="corr-1",
        authenticated_user=UserData(user_id=USER_ID, tenant_id=TENANT_ID),
    )
    issuer = RuntimePolicyEnforcer()
    issued = PolicyDecision(
        decision_id="policy-1",
        policy_version="fixture",
        allowed=True,
        runtime_constraints={
            "authorized_user_id": ctx.user_id,
            "authorized_tenant_id": ctx.tenant_id,
            "authorized_session_id": ctx.session_id,
            "correlation_id": ctx.correlation_id,
            "max_model_calls": 5,
        },
    )
    issuer._record_issued_model_decision(issued)
    issuer.bind_chat_model_policy(context=ctx, decision=issued)
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "hello"}],
        context=ctx,
        preferred_provider="ollama",
        preferred_model="llama3",
    )
    # Stream contract tests validate provider output, not persona DB reads.
    request.persona_snapshot = PersonaExecutionSnapshot(
        user_id=USER_ID, tenant_id=TENANT_ID, status="none",
    )
    return request


def _make_decision() -> ExecutionDecision:
    decision = MagicMock(spec=ExecutionDecision)
    decision.topology = ExecutionTopology.DIRECT
    decision.is_graph_required = False
    decision.memory_recall_required = True
    decision.memory_write_allowed = True
    decision.execution_mode = MagicMock(value="normal")
    decision.intent = "general_assist"
    decision.policy_decision_id = "policy-1"
    decision.required_capabilities = []
    decision.forbidden_capabilities = []
    decision.tool_requirements = []
    decision.plugin_candidates = []
    decision.policy_constraints = {}
    decision.time_budget_ms = 60000
    decision.max_steps = 5
    decision.max_model_calls = 5
    decision.token_budget = 4096
    decision.reasoning_depth = "standard"
    decision.reasoning_modes = []
    decision.workflow_id = None
    decision.workflow_version = None
    decision.requires_human_gate = False
    decision.requires_resumability = False
    decision.policy_version = "v1"
    decision.policy_reason_codes = []
    decision.reason_codes = []
    decision.risk_level = MagicMock(value="low")
    decision.memory_top_k = 5
    decision.memory_scope = "user"
    decision.cognitive_context = None
    return decision


def _make_plan() -> AuthorizedExecutionPlan:
    return AuthorizedExecutionPlan(
        execution_id=f"exec-req-1-{uuid4().hex}",
        policy_decision_id="policy-1",
        authorized_user_id=USER_ID,
        authorized_tenant_id=TENANT_ID,
        authorized_session_id="session-1",
        topology=ExecutionTopology.DIRECT,
        allowed_capabilities=[],
        allowed_tools=[],
        allowed_plugins=[],
        allowed_agents=[],
        budget=ExecutionBudget(
            max_duration_ms=60000,
            max_model_calls=5,
            max_tool_calls=5,
            max_reasoning_steps=5,
            max_output_tokens=4096,
        ),
        memory_scope="user",
        reasoning_modes=[],
        workflow_id=None,
        degraded_allowed=True,
        degradation_state=MagicMock(),
        audit_context={},
    )


def _fake_stream_chunks() -> list[ChatStreamChunk]:
    return [
        ChatStreamChunk(type="content", content="Hello", correlation_id="corr-1"),
        ChatStreamChunk(type="content", content=" world", correlation_id="corr-1"),
    ]


async def _collect_stream(
    runtime: ChatRuntime,
    request: ChatExecutionRequest,
    decision: ExecutionDecision,
    plan: AuthorizedExecutionPlan,
    fake_stream,
    *,
    persist_memory=None,
    resolved_memory_meta: Optional[Dict[str, Any]] = None,
) -> list[ChatStreamChunk]:
    memory_persist = persist_memory or AsyncMock()
    memory_meta = resolved_memory_meta or {
        "memory_recall_status": "success",
        "memory_recall_count": 0,
        "memory_persistence_status": "skipped",
    }
    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                with patch.object(
                    runtime,
                    "_consume_resolved_memory",
                    new_callable=AsyncMock,
                    return_value=memory_meta,
                ):
                    with patch.object(runtime, "_run_simple_stream", side_effect=fake_stream):
                        with patch.object(runtime, "_persist_memory", memory_persist):
                            with patch.object(runtime, "_record_trajectory_completion"):
                                with patch.object(runtime, "_record_execution_outcome"):
                                    with patch.object(runtime._emitter, "emit"):
                                        return [
                                            chunk
                                            async for chunk in runtime.execute_stream(request)
                                        ]


@pytest.mark.asyncio
async def test_execute_stream_assigns_canonical_sequence_and_ids():
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        for chunk in _fake_stream_chunks():
            yield chunk

    chunks = await _collect_stream(runtime, request, decision, plan, fake_stream)

    assert len(chunks) == 3
    assert chunks[0].sequence == 0
    assert chunks[1].sequence == 1
    assert chunks[2].sequence == 2

    event_ids = [chunk.event_id for chunk in chunks]
    assert len(event_ids) == len(set(event_ids)), "event_id must be unique"

    for chunk in chunks:
        assert chunk.correlation_id == "corr-1"
        assert chunk.request_id == "req-1"
        assert chunk.response_id == "req-1"
        assert chunk.conversation_id == CONVERSATION_ID
        assert isinstance(chunk.timestamp, datetime.datetime)

    assert len(gateway.calls) == 1
    assert gateway.calls[0]["user_text"] == "hello"
    assert gateway.calls[0]["assistant_text"] == "Hello world"
    assert gateway.calls[0]["response_metadata"]["trajectory_id"]


@pytest.mark.asyncio
async def test_execute_stream_emits_exactly_one_complete_on_success():
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="content", content="hi", correlation_id="corr-1")

    chunks = await _collect_stream(runtime, request, decision, plan, fake_stream)

    complete_chunks = [chunk for chunk in chunks if chunk.type == ChatStreamEventType.COMPLETE]
    assert len(complete_chunks) == 1
    assert len(gateway.calls) == 1
    assert complete_chunks[0].metadata["transcript_persistence_status"] == "persisted"
    assert complete_chunks[0].metadata["transcript_persisted_count"] == 2
    assert complete_chunks[0].metadata["user_message_id"] == USER_MESSAGE_ID
    assert complete_chunks[0].metadata["assistant_message_id"] == ASSISTANT_MESSAGE_ID


@pytest.mark.asyncio
async def test_execute_stream_emits_complete_on_generation_failure():
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="error", content="boom", correlation_id="corr-1")

    chunks = await _collect_stream(runtime, request, decision, plan, fake_stream)

    assert chunks[0].type == ChatStreamEventType.ERROR
    assert chunks[1].type == ChatStreamEventType.COMPLETE
    assert len([chunk for chunk in chunks if chunk.type == ChatStreamEventType.COMPLETE]) == 1
    assert gateway.calls == []
    assert chunks[-1].metadata["transcript_persistence_status"] == "skipped"


@pytest.mark.asyncio
async def test_execute_stream_handles_memory_persistence_failure_as_degraded():
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="content", content="hi", correlation_id="corr-1")

    async def fail_persistence(request, text, meta, plan):
        meta["memory_persistence_status"] = "failed"
        meta["memory_degraded"] = True
        meta["memory_degradation_reason"] = "memory_persistence_failed"
        return {
            "status": "failed",
            "reason": "memory_persistence_failed",
            "persisted": 0,
        }

    chunks = await _collect_stream(
        runtime,
        request,
        decision,
        plan,
        fake_stream,
        persist_memory=AsyncMock(side_effect=fail_persistence),
    )

    terminal_meta = chunks[-1].metadata
    assert terminal_meta["status"] == "degraded"
    assert terminal_meta["memory_persistence_status"] == "failed"
    assert terminal_meta["transcript_persistence_status"] == "persisted"
    assert terminal_meta["degradation_reason"] == "memory_persistence_failed"
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_execute_stream_does_not_persist_or_complete_when_cancelled():
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="content", content="hi", correlation_id="corr-1")
        raise asyncio.CancelledError()

    persist_memory = AsyncMock()
    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                with patch.object(
                    runtime,
                    "_consume_resolved_memory",
                    new_callable=AsyncMock,
                    return_value={},
                ):
                    with patch.object(runtime, "_run_simple_stream", side_effect=fake_stream):
                        with patch.object(runtime, "_persist_memory", persist_memory):
                            with patch.object(runtime, "_record_trajectory_completion"):
                                with patch.object(runtime, "_record_execution_outcome"):
                                    with patch.object(runtime._emitter, "emit"):
                                        with pytest.raises(asyncio.CancelledError):
                                            async for _ in runtime.execute_stream(request):
                                                pass

    assert gateway.calls == []
    persist_memory.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_stream_terminal_complete_metadata_is_complete():
    runtime, _ = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="content", content="hi", correlation_id="corr-1")

    chunks = await _collect_stream(runtime, request, decision, plan, fake_stream)
    complete_chunks = [chunk for chunk in chunks if chunk.type == ChatStreamEventType.COMPLETE]
    assert len(complete_chunks) == 1
    meta = complete_chunks[0].metadata
    expected_keys = [
        "correlation_id",
        "request_id",
        "response_id",
        "conversation_id",
        "assistant_message_id",
        "user_message_id",
        "requested_provider",
        "requested_model",
        "actual_provider",
        "actual_model",
        "runtime_engine",
        "protocol",
        "locality",
        "response_source",
        "fallback_level",
        "fallback_reason",
        "used_fallback",
        "degraded_mode",
        "degradation_reason",
        "mode",
        "latency_ms",
        "memory_recall_count",
        "memory_recall_status",
        "memory_persistence_status",
        "transcript_persistence_status",
        "transcript_persistence_reason",
        "transcript_persisted_count",
        "status",
    ]
    for key in expected_keys:
        assert key in meta, f"terminal metadata missing {key}"


@pytest.mark.asyncio
async def test_execute_stream_surfaces_continuity_and_capability_receipts():
    runtime, _ = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    decision.required_capabilities = ["memory.read"]
    decision.forbidden_capabilities = ["external.write"]
    decision.tool_requirements = ["calendar.lookup"]
    decision.plugin_candidates = ["calendar"]
    decision.requires_human_gate = True
    plan = _make_plan()
    plan.allowed_capabilities = ["memory.read"]
    plan.allowed_tools = ["calendar.lookup"]
    plan.allowed_plugins = ["calendar"]
    plan.allowed_agents = ["planner"]

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="content", content="hi", correlation_id="corr-1")

    continuity = {
        "memory_recall_status": "success",
        "memory_recall_count": 1,
        "memory_persistence_status": "skipped",
        "proactive_continuity": {
            "candidates": [
                {
                    "id": "loop-1",
                    "subject": "Follow up on the interview",
                    "source_type": "open_loop",
                    "utility": 0.91,
                    "confidence": 0.97,
                    "urgency": "high",
                    "execution_authorized": False,
                }
            ]
        },
        "continuity_primary_candidate_id": "loop-1",
        "continuity_ambiguous": False,
        "continuity_agenda_reason_codes": ["clear_primary_candidate"],
    }

    chunks = await _collect_stream(
        runtime,
        request,
        decision,
        plan,
        fake_stream,
        resolved_memory_meta=continuity,
    )

    meta = chunks[-1].metadata
    assert meta["proactive_continuity"]["candidates"][0]["id"] == "loop-1"
    assert meta["continuity_primary_candidate_id"] == "loop-1"
    assert meta["continuity_ambiguous"] is False

    receipt = meta["capability_receipt"]
    assert receipt["allowed_capabilities"] == ["memory.read"]
    assert receipt["forbidden_capabilities"] == ["external.write"]
    assert receipt["allowed_tools"] == ["calendar.lookup"]
    assert receipt["allowed_plugins"] == ["calendar"]
    assert receipt["allowed_agents"] == ["planner"]
    assert receipt["requires_human_gate"] is True
    assert receipt["policy_decision_id"] == "policy-1"


@pytest.mark.asyncio
async def test_execute_stream_transcript_failure_is_separate_from_memory_truth():
    gateway = _TranscriptGateway(
        TranscriptPersistenceResult(
            status="failed",
            conversation_id=CONVERSATION_ID,
            user_message_id=USER_MESSAGE_ID,
            assistant_message_id=ASSISTANT_MESSAGE_ID,
            persisted_messages=1,
            reason="assistant_message_persistence_failed",
            error_type="RuntimeError",
        )
    )
    runtime, _ = _make_runtime(gateway)
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="content", content="hi", correlation_id="corr-1")

    async def memory_ok(request, text, meta, plan):
        meta["memory_persistence_status"] = "persisted"
        return {"status": "persisted", "persisted": 1}

    chunks = await _collect_stream(
        runtime,
        request,
        decision,
        plan,
        fake_stream,
        persist_memory=AsyncMock(side_effect=memory_ok),
    )

    meta = chunks[-1].metadata
    assert meta["memory_persistence_status"] == "persisted"
    assert meta["transcript_persistence_status"] == "failed"
    assert meta["transcript_persisted_count"] == 1
    assert meta["transcript_persistence_reason"] == "assistant_message_persistence_failed"
    assert meta["status"] == "degraded"
    assert meta["degradation_reason"] == "assistant_message_persistence_failed"

    # The canonical runtime's failed transcript write must not be rewritten
    # by the AG-UI transport into a successful, persisted assistant turn.
    projection = AGUIEventProjection(thread_id=CONVERSATION_ID, run_id="run-failed-write")
    projected = [projection.begin()]
    for runtime_chunk in chunks:
        projected.extend(projection.project(runtime_chunk))
    assert [event["type"] for event in projected].count("RUN_ERROR") == 1
    assert "RUN_FINISHED" not in [event["type"] for event in projected]
    assert "karen.execution_receipt.v1" not in str(projected)
    assert projected[-1]["code"] == "CHAT_TRANSCRIPT_PERSISTENCE_FAILED"


@pytest.mark.asyncio
async def test_execute_stream_idempotent_replay_is_not_degraded():
    gateway = _TranscriptGateway(
        TranscriptPersistenceResult(
            status="already_persisted",
            conversation_id=CONVERSATION_ID,
            user_message_id=USER_MESSAGE_ID,
            assistant_message_id=ASSISTANT_MESSAGE_ID,
            persisted_messages=0,
            reason="idempotent_replay",
        )
    )
    runtime, _ = _make_runtime(gateway)
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="content", content="hi", correlation_id="corr-1")

    chunks = await _collect_stream(runtime, request, decision, plan, fake_stream)
    meta = chunks[-1].metadata
    assert meta["transcript_persistence_status"] == "already_persisted"
    assert meta["transcript_persisted_count"] == 0
    assert meta["degraded_mode"] is False
    assert meta["status"] == "ok"


@pytest.mark.asyncio
async def test_execute_stream_ignores_inner_complete_events():
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="content", content="hi", correlation_id="corr-1")
        yield ChatStreamChunk(type="complete", content="", correlation_id="corr-1")
        yield ChatStreamChunk(type="content", content=" there", correlation_id="corr-1")

    chunks = await _collect_stream(runtime, request, decision, plan, fake_stream)
    complete_chunks = [chunk for chunk in chunks if chunk.type == ChatStreamEventType.COMPLETE]
    content_chunks = [chunk for chunk in chunks if chunk.type == ChatStreamEventType.CONTENT]
    assert len(complete_chunks) == 1
    assert len(content_chunks) == 2
    assert len(gateway.calls) == 1
    assert gateway.calls[0]["assistant_text"] == "hi there"


@pytest.mark.asyncio
async def test_execute_stream_gate_emits_error_and_complete_without_persistence():
    runtime, gateway = _make_runtime()
    request = _make_request()
    gate = MagicMock()
    gate.mode = "maintenance"
    gate.message = "Service unavailable"

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=gate):
        with patch.object(runtime._emitter, "emit"):
            chunks = [chunk async for chunk in runtime.execute_stream(request)]

    assert len(chunks) == 2
    assert chunks[0].type == ChatStreamEventType.ERROR
    assert chunks[1].type == ChatStreamEventType.COMPLETE
    assert len([chunk for chunk in chunks if chunk.type == ChatStreamEventType.COMPLETE]) == 1
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_execute_stream_human_gate_stops_before_execution_and_persistence():
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    decision.requires_human_gate = True
    plan = _make_plan()
    approval = ApprovalRequiredResponse(
        approval_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        status="pending",
        intent="general_assist",
        risk_level="high",
        reason_codes=["human_gate_required"],
    )
    run_simple_stream = MagicMock()

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_record_user_behavior_observation", new_callable=AsyncMock):
                with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                    with patch.object(
                        runtime,
                        "_resolve_human_approval_gate",
                        new_callable=AsyncMock,
                        return_value=approval,
                    ):
                        with patch.object(runtime, "_run_simple_stream", run_simple_stream):
                            with patch.object(runtime, "_persist_memory", new_callable=AsyncMock) as persist_memory:
                                with patch.object(runtime, "_persist_transcript", new_callable=AsyncMock) as persist_transcript:
                                    with patch.object(runtime._emitter, "emit"):
                                        chunks = [
                                            chunk
                                            async for chunk in runtime.execute_stream(request)
                                        ]

    assert [chunk.type for chunk in chunks] == [
        ChatStreamEventType.APPROVAL,
        ChatStreamEventType.COMPLETE,
    ]
    assert chunks[0].metadata["approval_id"] == approval.approval_id
    assert chunks[1].metadata["status"] == "gate"
    assert chunks[1].metadata["approval_status"] == "pending"
    run_simple_stream.assert_not_called()
    persist_memory.assert_not_awaited()
    persist_transcript.assert_not_awaited()
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_execute_human_gate_returns_gate_without_model_execution():
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    decision.requires_human_gate = True
    plan = _make_plan()
    approval = ApprovalRequiredResponse(
        approval_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        status="pending",
        intent="general_assist",
        risk_level="high",
    )

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_record_user_behavior_observation", new_callable=AsyncMock):
                with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                    with patch.object(
                        runtime,
                        "_resolve_human_approval_gate",
                        new_callable=AsyncMock,
                        return_value=approval,
                    ):
                        with patch.object(runtime, "_run_simple", new_callable=AsyncMock) as run_simple:
                            with patch.object(runtime._emitter, "emit"):
                                result = await runtime.execute(request)

    assert result.status == ChatExecutionStatus.GATE
    assert result.gate_response is approval
    assert result.metadata.mode == "approval_required"
    assert result.metadata.extra["approval_id"] == approval.approval_id
    run_simple.assert_not_awaited()
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_execute_stream_preserves_rich_results_in_terminal_metadata_and_transcript():
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    rich = {
        "structured_content": {"summary": {"status": "ready"}},
        "actions": [{"type": "continue", "description": "Continue"}],
        "citations": [{"id": "c1", "url": "https://example.com"}],
        "sources": [{"id": "s1", "url": "https://example.com/source"}],
        "attachments": [{"id": "a1", "name": "report.pdf"}],
        "artifacts": [{"id": "r1", "title": "Report"}],
    }

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(
            type="content",
            content="hi",
            correlation_id="corr-1",
            metadata=rich,
        )

    chunks = await _collect_stream(runtime, request, decision, plan, fake_stream)

    terminal = chunks[-1].metadata
    for key, value in rich.items():
        assert terminal[key] == value

    persisted = gateway.calls[0]["response_metadata"]
    for key, value in rich.items():
        assert persisted[key] == value


@pytest.mark.asyncio
async def test_stream_personal_identity_uses_authorized_evidence_without_model_call():
    """Provider degradation cannot turn a verified identity into LLM speculation."""
    from ai_karen_engine.core.context.contracts import (
        ContextEvidence, EvidenceScope, EvidenceSource,
    )

    runtime, gateway = _make_runtime()
    request = _make_request()
    request.messages = [{"role": "user", "content": "Who am I?"}]
    decision = _make_decision()
    decision.intent = "memory.recall"
    decision.policy_constraints = {}
    decision.cognitive_context = MagicMock()
    decision.cognitive_context.tenant_id = TENANT_ID
    decision.cognitive_context.user_id = USER_ID
    decision.cognitive_context.authorized_sources = ["memory"]
    decision.cognitive_context.denied_sources = []
    decision.cognitive_context.unresolved_sources = []
    decision.cognitive_context.evidence = [
        ContextEvidence(
            evidence_id="verified-name",
            source=EvidenceSource.MEMORY,
            content="preferred_name: Aurelia",
            scope=EvidenceScope(tenant_id=TENANT_ID, user_id=USER_ID),
        ),
    ]
    plan = _make_plan()

    async def forbidden_model(*args, **kwargs):
        raise AssertionError("personal identity recall must not reach a model")
        yield  # pragma: no cover

    chunks = await _collect_stream(
        runtime, request, decision, plan, forbidden_model,
    )
    content = "".join(c.content for c in chunks if c.type == "content")
    assert "Aurelia" in content
    assert len([c for c in chunks if c.type == ChatStreamEventType.COMPLETE]) == 1
    assert gateway.calls[0]["assistant_text"] == content
    assert gateway.calls[0]["response_metadata"]["response_source"] == "authorized_memory_evidence"



@pytest.mark.asyncio
async def test_status_only_stream_is_explicit_failure_not_successful_empty_answer():
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def status_only(*args, **kwargs):
        yield ChatStreamChunk(
            type="status", content="Waiting for model",
            correlation_id="corr-1",
        )

    chunks = await _collect_stream(runtime, request, decision, plan, status_only)
    assert [chunk.type for chunk in chunks] == [
        ChatStreamEventType.STATUS,
        ChatStreamEventType.STATUS,
        ChatStreamEventType.ERROR,
        ChatStreamEventType.COMPLETE,
    ]
    failure = chunks[2]
    assert failure.metadata["error_code"] == "CHAT_EMPTY_STREAM"
    assert failure.metadata["error_type"] == "EmptyGeneration"
    assert failure.metadata["correlation_id"] == "corr-1"
    assert failure.metadata["requested_provider"] == "ollama"
    assert failure.metadata["requested_model"] == "llama3"
    assert failure.content == "The selected runtime produced no assistant response."
    assert chunks[-1].metadata["transcript_persistence_status"] == "skipped"
    assert chunks[-1].metadata["status"] == "error"
    assert chunks[-1].metadata["failure_category"] == "degraded_runtime"
    assert gateway.calls == []



@pytest.mark.asyncio
async def test_empty_model_output_is_not_success():
    """KCON-770/04: zero model text is a retryable failure, never a saved answer."""
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def empty_model_stream(*args, **kwargs):
        if False:
            yield ChatStreamChunk(type="content", content="unreachable")

    chunks = await _collect_stream(
        runtime, request, decision, plan, empty_model_stream,
    )
    errors = [chunk for chunk in chunks if chunk.type == ChatStreamEventType.ERROR]
    completes = [chunk for chunk in chunks if chunk.type == ChatStreamEventType.COMPLETE]
    assert len(errors) == 1
    assert errors[0].metadata["error_code"] == "CHAT_EMPTY_STREAM"
    assert errors[0].metadata["error_type"] == "EmptyGeneration"
    assert "no assistant response" in errors[0].content.lower()
    assert len(completes) == 1
    assert completes[0].metadata["status"] == "error"
    assert completes[0].metadata["transcript_persistence_status"] == "skipped"
    assert completes[0].metadata["transcript_persisted_count"] == 0
    assert not any(
        chunk.type == ChatStreamEventType.CONTENT and chunk.content.strip()
        for chunk in chunks
    )
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_upstream_stream_error_is_not_replaced_with_second_empty_error():
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def upstream_error(*args, **kwargs):
        yield ChatStreamChunk(
            type="error", content="Model unavailable",
            correlation_id="corr-1",
            metadata={"error_code": "MODEL_UNAVAILABLE"},
        )

    chunks = await _collect_stream(runtime, request, decision, plan, upstream_error)
    errors = [chunk for chunk in chunks if chunk.type == ChatStreamEventType.ERROR]
    assert len(errors) == 1
    assert errors[0].metadata["error_code"] == "MODEL_UNAVAILABLE"
    assert chunks[-1].type == ChatStreamEventType.COMPLETE
    assert chunks[-1].metadata["status"] == "error"
    assert chunks[-1].metadata["failure_category"] == "degraded_runtime"
    assert chunks[-1].metadata["error_code"] == "MODEL_UNAVAILABLE"
    assert chunks[-1].metadata["error_type"] == "UpstreamStreamError"
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_whitespace_only_assistant_stream_does_not_persist_as_model_reply():
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def whitespace(*args, **kwargs):
        yield ChatStreamChunk(
            type="content", content="   ", correlation_id="corr-1",
        )

    memory_write = AsyncMock()
    chunks = await _collect_stream(
        runtime, request, decision, plan, whitespace,
        persist_memory=memory_write,
    )
    memory_write.assert_not_awaited()
    assert [c.type for c in chunks] == [
        ChatStreamEventType.STATUS,
        ChatStreamEventType.CONTENT,
        ChatStreamEventType.ERROR,
        ChatStreamEventType.COMPLETE,
    ]
    assert chunks[2].metadata["error_code"] == "CHAT_EMPTY_STREAM"
    assert gateway.calls == []



@pytest.mark.asyncio
async def test_partial_content_then_error_never_persists_failed_assistant_turn():
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def partial_then_error(*args, **kwargs):
        yield ChatStreamChunk(
            type="content", content="Unfinished thought",
            correlation_id="corr-1",
        )
        yield ChatStreamChunk(
            type="error", content="Provider disconnected",
            correlation_id="corr-1",
            metadata={
                "error_code": "PROVIDER_DISCONNECTED",
                "error_type": "ProviderConnectionError",
            },
        )

    memory_write = AsyncMock()
    chunks = await _collect_stream(
        runtime, request, decision, plan, partial_then_error,
        persist_memory=memory_write,
    )

    assert [chunk.type for chunk in chunks] == [
        ChatStreamEventType.STATUS,
        ChatStreamEventType.CONTENT,
        ChatStreamEventType.ERROR,
        ChatStreamEventType.COMPLETE,
    ]
    assert chunks[2].metadata["error_code"] == "PROVIDER_DISCONNECTED"
    assert chunks[-1].metadata["status"] == "error"
    assert chunks[-1].metadata["transcript_persistence_status"] == "skipped"
    assert chunks[-1].metadata["failure_category"] == "degraded_runtime"
    assert chunks[-1].metadata["error_code"] == "PROVIDER_DISCONNECTED"
    assert chunks[-1].metadata["error_type"] == "ProviderConnectionError"
    assert gateway.calls == []
    memory_write.assert_not_awaited()



@pytest.mark.asyncio
async def test_stream_execution_exception_uses_canonical_runtime_fallback():
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def failing_stream(*args, **kwargs):
        raise RuntimeError("secret-upstream-detail")
        if False:
            yield ChatStreamChunk(
                type="content",
                content="unreachable",
                correlation_id="corr-1",
            )

    fallback = MagicMock()
    fallback.answer = "Recovered through fallback"
    fallback.metadata.to_dict.return_value = {
        "actual_provider": "vllm",
        "actual_model": "fallback-model",
        "runtime_engine": "vllm",
        "response_source": "model",
        "fallback_level": 1,
        "degraded_mode": True,
        "degradation_reason": "primary_provider_failed",
    }

    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.build_runtime_fallback",
        new_callable=AsyncMock,
        return_value=fallback,
    ) as fallback_builder:
        chunks = await _collect_stream(
            runtime,
            request,
            decision,
            plan,
            failing_stream,
        )

    fallback_builder.assert_awaited_once()
    contents = [
        chunk.content
        for chunk in chunks
        if chunk.type == ChatStreamEventType.CONTENT
    ]
    assert contents == ["Recovered through fallback"]
    assert all("secret-upstream-detail" not in chunk.content for chunk in chunks)
    assert not [
        chunk for chunk in chunks
        if chunk.type == ChatStreamEventType.ERROR
    ]
    assert chunks[-1].type == ChatStreamEventType.COMPLETE
    assert chunks[-1].metadata["fallback_level"] == 1
    assert chunks[-1].metadata["degraded_mode"] is True
    assert gateway.calls[0]["assistant_text"] == "Recovered through fallback"


@pytest.mark.asyncio
async def test_stream_completion_exposes_safe_projection_targets_not_raw_receipts():
    runtime, _gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="content", content="Hello", correlation_id="corr-1")

    async def degraded_projection(_request, _text, metadata, _plan):
        metadata["memory_persistence_status"] = "persisted_projection_degraded"
        metadata["memory_degraded"] = True
        metadata["memory_degradation_reason"] = "memory_projection_failed"
        metadata["memory_projection_targets"] = [
            {"target": "stm", "success_count": 1, "failure_count": 0},
            {"target": "memory_graph", "success_count": 0, "failure_count": 1},
        ]
        return {
            "persisted": 1,
            "receipts": [{"memory_id": "private-never-expose"}],
        }

    chunks = await _collect_stream(
        runtime,
        request,
        decision,
        plan,
        fake_stream,
        persist_memory=AsyncMock(side_effect=degraded_projection),
    )
    terminal = chunks[-1].metadata

    assert terminal["memory_persistence_status"] == "persisted_projection_degraded"
    assert terminal["memory_projection_targets"] == [
        {"target": "stm", "success_count": 1, "failure_count": 0},
        {"target": "memory_graph", "success_count": 0, "failure_count": 1},
    ]
    assert "private-never-expose" not in str(terminal)


@pytest.mark.asyncio
async def test_kcon765_stream_receipt_measures_ingress_to_first_content_and_completion():
    """The canonical receipt includes preprocessing time, not just model execution."""
    runtime, _ = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="content", content="", correlation_id="corr-1")
        yield ChatStreamChunk(type="content", content="Measured", correlation_id="corr-1")

    chunks = await _collect_stream(runtime, request, decision, plan, fake_stream)
    receipt = chunks[-1].metadata
    first = receipt["request_to_first_content_ms"]
    assert isinstance(first, float)
    assert first >= 0.0
    assert receipt["request_to_first_presentation_ms"] is None
    assert receipt["latency_ms"] >= first
    assert receipt["correlation_id"] == "corr-1"
    assert receipt["request_id"] == "req-1"
    spans = receipt["consumer_insights"]
    assert spans is not None


@pytest.mark.asyncio
async def test_kcon765_first_verified_presentation_is_timed_but_unverified_is_not():
    runtime, _ = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="content", content="Measured", correlation_id="corr-1")
        yield ChatStreamChunk(
            type="presentation", content="", correlation_id="corr-1",
            metadata={"presentation_verified": False, "presentation": {"unsafe": True}},
        )
        yield ChatStreamChunk(
            type="presentation", content="", correlation_id="corr-1",
            metadata={"presentation_verified": True, "presentation": {"safe": True}},
        )

    validated = {"presentation_id": "verified-one", "component_type": "time.current"}
    with patch(
        "ai_karen_engine.core.runtime.presentation_contract.validate_presentation",
        return_value=validated,
    ):
        chunks = await _collect_stream(runtime, request, decision, plan, fake_stream)

    receipt = chunks[-1].metadata
    assert isinstance(receipt["request_to_first_content_ms"], float)
    assert isinstance(receipt["request_to_first_presentation_ms"], float)
    assert receipt["request_to_first_presentation_ms"] >= receipt["request_to_first_content_ms"]
    assert receipt["latency_ms"] >= receipt["request_to_first_presentation_ms"]


@pytest.mark.asyncio
async def test_kcon765_failed_stream_does_not_invent_first_content_or_presentation():
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="error", content="unavailable", correlation_id="corr-1")

    chunks = await _collect_stream(runtime, request, decision, plan, fake_stream)
    receipt = chunks[-1].metadata
    assert receipt["status"] == "error"
    assert receipt["request_to_first_content_ms"] is None
    assert receipt["request_to_first_presentation_ms"] is None
    assert receipt["latency_ms"] >= 0
    assert gateway.calls == []


# KCOG-01C1B2C2: cancellation is terminal evidence, never a model outcome.
# The ordinary run coordinator remains the authority for request-stop races.


def _b2c2_store(runtime: ChatRuntime) -> InMemoryTrajectoryStore:
    store = InMemoryTrajectoryStore()
    runtime._trajectory_recorder = TrajectoryRecorder(store=store)
    return store


@pytest.mark.asyncio
async def test_b2c2_midstream_cancel_records_scoped_terminal_without_reply() -> None:
    runtime, gateway = _make_runtime()
    store = _b2c2_store(runtime)
    request = _make_request()
    decision = _make_decision()
    decision.memory_recall_required = False
    decision.memory_write_allowed = False
    plan = _make_plan()

    async def partial_then_cancel(*args, **kwargs):
        yield ChatStreamChunk(
            type="content", content="unfinished output", correlation_id="corr-1",
        )
        raise asyncio.CancelledError()

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                with patch.object(runtime, "_run_simple_stream", side_effect=partial_then_cancel):
                    with patch.object(runtime, "_persist_memory", new_callable=AsyncMock) as memory:
                        with patch.object(runtime, "_record_execution_outcome", new_callable=AsyncMock) as outcome:
                            with pytest.raises(asyncio.CancelledError):
                                async for _ in runtime.execute_stream(request):
                                    pass

    records = store.list_for_tenant(TENANT_ID)
    assert len(records) == 1
    record = records[0]
    assert record.execution_status == "cancelled"
    assert record.error_code == "CHAT_REQUEST_CANCELLED"
    assert record.completed_at is not None
    assert record.policy_decision_id == decision.policy_decision_id
    assert record.request_id == request.context.request_id
    assert record.correlation_id == request.context.correlation_id
    assert record.user_id == USER_ID
    assert record.actual_provider is None
    assert record.actual_model is None
    assert record.response_source is None
    assert record.degraded_mode is True
    assert record.degradation_reason == "request_cancelled"
    assert store.get(record.trajectory_id, tenant_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb") is None
    assert gateway.calls == []
    memory.assert_not_awaited()
    outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_b2c2_stream_close_is_cancelled_not_committed() -> None:
    runtime, gateway = _make_runtime()
    store = _b2c2_store(runtime)
    request = _make_request()
    decision = _make_decision()
    decision.memory_recall_required = False
    decision.memory_write_allowed = False
    plan = _make_plan()

    async def stream_then_more(*args, **kwargs):
        yield ChatStreamChunk(
            type="content", content="partial", correlation_id="corr-1",
        )
        await asyncio.Event().wait()

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                with patch.object(runtime, "_run_simple_stream", side_effect=stream_then_more):
                    with patch.object(runtime, "_record_execution_outcome", new_callable=AsyncMock) as outcome:
                        stream = runtime.execute_stream(request)
                        assert (await anext(stream)).type == ChatStreamEventType.STATUS
                        assert (await anext(stream)).type == ChatStreamEventType.CONTENT
                        await stream.aclose()

    records = store.list_for_tenant(TENANT_ID)
    assert len(records) == 1
    assert records[0].execution_status == "cancelled"
    assert records[0].error_code == "CHAT_REQUEST_CANCELLED"
    assert records[0].actual_provider is None
    assert gateway.calls == []
    outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_b2c2_cancelled_trajectory_scope_drift_and_write_failure_fail_closed() -> None:
    runtime, _ = _make_runtime()
    store = _b2c2_store(runtime)
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()
    meter = ExecutionBudgetMeter(plan.budget)
    meter.start()

    def trajectory(*, tenant_id: str = TENANT_ID, id_suffix: str) -> ExecutionTrajectory:
        return ExecutionTrajectory(
            trajectory_id=f"traj_cancel_{id_suffix}",
            request_id=request.context.request_id,
            correlation_id=request.context.correlation_id,
            tenant_id=tenant_id,
            user_id=request.context.user_id,
            session_id=request.context.session_id,
            conversation_id=request.context.conversation_id,
        )

    wrong = trajectory(tenant_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", id_suffix="wrong")
    await runtime._record_cancelled_trajectory(
        wrong, decision, request, plan, meter, 1.0,
    )
    assert wrong.execution_status is None
    assert store.list_for_tenant(wrong.tenant_id) == []

    matching = trajectory(id_suffix="valid")
    await runtime._record_cancelled_trajectory(
        matching, decision, request, plan, meter, 1.0,
    )
    assert matching.execution_status == "cancelled"
    assert store.get(matching.trajectory_id, tenant_id=TENANT_ID) is matching

    class RejectingStore(InMemoryTrajectoryStore):
        def save(self, trajectory: ExecutionTrajectory) -> None:
            raise RuntimeError("test-only storage failure")

    rejecting = RejectingStore()
    runtime._trajectory_recorder = TrajectoryRecorder(store=rejecting)
    another = trajectory(id_suffix="failed")
    await runtime._record_cancelled_trajectory(
        another, decision, request, plan, meter, 1.0,
    )
    assert another.execution_status == "cancelled"
    assert rejecting.get(another.trajectory_id, tenant_id=TENANT_ID) is None


@pytest.mark.asyncio
async def test_b2c2_nonstream_cancel_does_not_trigger_fallback_or_saved_answer() -> None:
    runtime, gateway = _make_runtime()
    store = _b2c2_store(runtime)
    request = _make_request()
    decision = _make_decision()
    decision.memory_recall_required = False
    decision.memory_write_allowed = False
    plan = _make_plan()

    async def cancelled_generation(*args, **kwargs):
        raise asyncio.CancelledError()

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_freeze_persona_snapshot", new_callable=AsyncMock):
            with patch.object(runtime, "_prepare_conversation_continuation", new_callable=AsyncMock):
                with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
                    with patch.object(runtime, "_record_user_behavior_observation", new_callable=AsyncMock):
                        with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                            with patch.object(runtime, "_grounded_personal_response", return_value=None):
                                with patch.object(runtime, "_is_explicit_save_turn", return_value=False):
                                    with patch("ai_karen_engine.core.runtime.chat_runtime.get_direct_capability_executor") as direct:
                                        direct.return_value.can_handle.return_value = False
                                        with patch.object(runtime, "_run_simple", side_effect=cancelled_generation):
                                            with patch.object(runtime, "_persist_transcript", new_callable=AsyncMock) as persist:
                                                with patch.object(runtime, "_record_execution_outcome", new_callable=AsyncMock) as outcome:
                                                    with pytest.raises(asyncio.CancelledError):
                                                        await runtime.execute(request)
    records = store.list_for_tenant(TENANT_ID)
    assert len(records) == 1
    assert records[0].execution_status == "cancelled"
    assert records[0].error_code == "CHAT_REQUEST_CANCELLED"
    assert records[0].actual_model is None
    assert gateway.calls == []
    persist.assert_not_awaited()
    outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_b2c2_real_task_cancel_after_first_token_is_terminal() -> None:
    """Cancel the consumer task, not merely raise a synthetic exception."""
    runtime, gateway = _make_runtime()
    store = _b2c2_store(runtime)
    request = _make_request()
    decision = _make_decision()
    decision.memory_recall_required = False
    decision.memory_write_allowed = False
    plan = _make_plan()
    content_seen = asyncio.Event()
    provider_cancelled = asyncio.Event()
    never_complete = asyncio.Event()

    async def blocked_provider(*args, **kwargs):
        try:
            yield ChatStreamChunk(
                type="content", content="partial", correlation_id="corr-1",
            )
            await never_complete.wait()
        finally:
            provider_cancelled.set()

    async def consume():
        async for chunk in runtime.execute_stream(request):
            if chunk.type == ChatStreamEventType.CONTENT:
                content_seen.set()

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                with patch.object(runtime, "_run_simple_stream", side_effect=blocked_provider):
                    with patch.object(runtime, "_record_execution_outcome", new_callable=AsyncMock) as outcome:
                        task = asyncio.create_task(consume())
                        try:
                            await asyncio.wait_for(content_seen.wait(), timeout=5)
                            task.cancel()
                            with pytest.raises(asyncio.CancelledError):
                                await task
                        finally:
                            if not task.done():
                                task.cancel()
                                await asyncio.gather(task, return_exceptions=True)
    records = store.list_for_tenant(TENANT_ID)
    assert len(records) == 1
    assert records[0].execution_status == "cancelled"
    assert records[0].error_code == "CHAT_REQUEST_CANCELLED"
    assert records[0].actual_provider is None
    assert gateway.calls == []
    outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_b2c2_close_immediately_after_status_records_cancelled() -> None:
    """The initial STATUS yield is already inside the allocated trajectory."""
    runtime, gateway = _make_runtime()
    store = _b2c2_store(runtime)
    request = _make_request()
    decision = _make_decision()
    decision.memory_recall_required = False
    decision.memory_write_allowed = False
    plan = _make_plan()

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                with patch.object(runtime, "_persist_transcript", new_callable=AsyncMock) as persist:
                    with patch.object(runtime, "_record_execution_outcome", new_callable=AsyncMock) as outcome:
                        stream = runtime.execute_stream(request)
                        assert (await anext(stream)).type == ChatStreamEventType.STATUS
                        await stream.aclose()

    records = store.list_for_tenant(TENANT_ID)
    assert len(records) == 1
    assert records[0].execution_status == "cancelled"
    assert records[0].error_code == "CHAT_REQUEST_CANCELLED"
    assert records[0].actual_model is None
    assert gateway.calls == []
    persist.assert_not_awaited()
    outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_b2c2_cancel_during_recall_records_terminal_without_generation() -> None:
    runtime, gateway = _make_runtime()
    store = _b2c2_store(runtime)
    request = _make_request()
    decision = _make_decision()
    decision.memory_recall_required = True
    decision.memory_write_allowed = False
    plan = _make_plan()
    recall_started = asyncio.Event()
    recall_release = asyncio.Event()

    async def blocked_recall(*args, **kwargs):
        recall_started.set()
        await recall_release.wait()
        return {}

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                with patch.object(runtime, "_consume_resolved_memory", side_effect=blocked_recall):
                    with patch.object(runtime, "_run_simple_stream", new_callable=AsyncMock) as generate:
                        with patch.object(runtime, "_persist_transcript", new_callable=AsyncMock) as persist:
                            with patch.object(runtime, "_record_execution_outcome", new_callable=AsyncMock) as outcome:
                                stream = runtime.execute_stream(request)
                                assert (await anext(stream)).type == ChatStreamEventType.STATUS
                                task = asyncio.create_task(anext(stream))
                                try:
                                    await asyncio.wait_for(recall_started.wait(), timeout=5)
                                    task.cancel()
                                    with pytest.raises(asyncio.CancelledError):
                                        await task
                                finally:
                                    if not task.done():
                                        task.cancel()
                                        await asyncio.gather(task, return_exceptions=True)
                                await stream.aclose()

    records = store.list_for_tenant(TENANT_ID)
    assert len(records) == 1
    assert records[0].execution_status == "cancelled"
    assert records[0].actual_provider is None
    assert records[0].error_code == "CHAT_REQUEST_CANCELLED"
    assert gateway.calls == []
    generate.assert_not_awaited()
    persist.assert_not_awaited()
    outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_b2c2_repeated_cancel_cannot_suppress_request_cancel_event() -> None:
    """The request-cancel observation must precede an interruptible DB await."""
    from ai_karen_engine.platform.observability.contracts import (
        EventType as RuntimeEventType,
    )

    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    decision.memory_recall_required = False
    decision.memory_write_allowed = False
    plan = _make_plan()
    content_seen = asyncio.Event()
    persistence_started = asyncio.Event()
    persistence_release = asyncio.Event()

    async def token_then_block(*args, **kwargs):
        yield ChatStreamChunk(
            type="content", content="partial", correlation_id="corr-1",
        )
        await asyncio.Event().wait()

    async def blocked_trajectory_write(*args, **kwargs):
        persistence_started.set()
        await persistence_release.wait()

    async def consume() -> None:
        async for chunk in runtime.execute_stream(request):
            if chunk.type == ChatStreamEventType.CONTENT:
                content_seen.set()

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                with patch.object(runtime, "_run_simple_stream", side_effect=token_then_block):
                    with patch.object(runtime, "_record_cancelled_trajectory", side_effect=blocked_trajectory_write):
                        with patch.object(runtime, "_record_execution_outcome", new_callable=AsyncMock) as outcome:
                            with patch.object(runtime._emitter, "emit") as emit:
                                task = asyncio.create_task(consume())
                                try:
                                    await asyncio.wait_for(content_seen.wait(), timeout=5)
                                    task.cancel()
                                    await asyncio.wait_for(persistence_started.wait(), timeout=5)
                                    assert any(
                                        call.args and call.args[0] == RuntimeEventType.REQUEST_CANCELLED
                                        for call in emit.call_args_list
                                    )
                                    task.cancel()
                                    with pytest.raises(asyncio.CancelledError):
                                        await task
                                finally:
                                    if not task.done():
                                        task.cancel()
                                        await asyncio.gather(task, return_exceptions=True)
    assert gateway.calls == []
    outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_b2c2_nonstream_cancel_during_authorized_fallback_is_terminal() -> None:
    runtime, gateway = _make_runtime()
    store = _b2c2_store(runtime)
    request = _make_request()
    decision = _make_decision()
    decision.memory_recall_required = False
    decision.memory_write_allowed = False
    plan = _make_plan()
    fallback_entered = asyncio.Event()

    async def primary_failure(*args, **kwargs):
        raise RuntimeError("primary failed")

    async def blocked_fallback(*args, **kwargs):
        fallback_entered.set()
        await asyncio.Event().wait()

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_freeze_persona_snapshot", new_callable=AsyncMock):
            with patch.object(runtime, "_prepare_conversation_continuation", new_callable=AsyncMock):
                with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
                    with patch.object(runtime, "_record_user_behavior_observation", new_callable=AsyncMock):
                        with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                            with patch.object(runtime, "_grounded_personal_response", return_value=None):
                                with patch.object(runtime, "_is_explicit_save_turn", return_value=False):
                                    with patch("ai_karen_engine.core.runtime.chat_runtime.get_direct_capability_executor") as direct:
                                        direct.return_value.can_handle.return_value = False
                                        with patch.object(runtime, "_run_simple", side_effect=primary_failure):
                                            with patch("ai_karen_engine.core.runtime.chat_runtime.build_runtime_fallback", side_effect=blocked_fallback):
                                                with patch.object(runtime, "_persist_transcript", new_callable=AsyncMock) as persist:
                                                    with patch.object(runtime, "_record_execution_outcome", new_callable=AsyncMock) as outcome:
                                                        task = asyncio.create_task(runtime.execute(request))
                                                        try:
                                                            await asyncio.wait_for(fallback_entered.wait(), timeout=5)
                                                            task.cancel()
                                                            with pytest.raises(asyncio.CancelledError):
                                                                await task
                                                        finally:
                                                            if not task.done():
                                                                task.cancel()
                                                                await asyncio.gather(task, return_exceptions=True)
    rows = store.list_for_tenant(TENANT_ID)
    assert len(rows) == 1
    assert rows[0].execution_status == "cancelled"
    assert rows[0].error_code == "CHAT_REQUEST_CANCELLED"
    assert rows[0].actual_model is None
    assert gateway.calls == []
    persist.assert_not_awaited()
    outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_b2c2_stream_cancel_during_authorized_fallback_is_terminal() -> None:
    runtime, gateway = _make_runtime()
    store = _b2c2_store(runtime)
    request = _make_request()
    decision = _make_decision()
    decision.memory_recall_required = False
    decision.memory_write_allowed = False
    plan = _make_plan()
    fallback_entered = asyncio.Event()

    async def primary_failure(*args, **kwargs):
        raise RuntimeError("primary failed")
        yield ChatStreamChunk(type="content", content="never", correlation_id="corr-1")

    async def blocked_fallback(*args, **kwargs):
        fallback_entered.set()
        await asyncio.Event().wait()

    async def consume():
        async for _ in runtime.execute_stream(request):
            pass

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                with patch.object(runtime, "_run_simple_stream", side_effect=primary_failure):
                    with patch("ai_karen_engine.core.runtime.chat_runtime.get_direct_capability_executor") as direct:
                        direct.return_value.can_handle.return_value = False
                        with patch("ai_karen_engine.core.runtime.chat_runtime.build_runtime_fallback", side_effect=blocked_fallback):
                            with patch.object(runtime, "_persist_transcript", new_callable=AsyncMock) as persist:
                                with patch.object(runtime, "_record_execution_outcome", new_callable=AsyncMock) as outcome:
                                    task = asyncio.create_task(consume())
                                    try:
                                        await asyncio.wait_for(fallback_entered.wait(), timeout=5)
                                        task.cancel()
                                        with pytest.raises(asyncio.CancelledError):
                                            await task
                                    finally:
                                        if not task.done():
                                            task.cancel()
                                            await asyncio.gather(task, return_exceptions=True)
    rows = store.list_for_tenant(TENANT_ID)
    assert len(rows) == 1
    assert rows[0].execution_status == "cancelled"
    assert rows[0].error_code == "CHAT_REQUEST_CANCELLED"
    assert rows[0].actual_provider is None
    assert gateway.calls == []
    persist.assert_not_awaited()
    outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_b2c2_close_at_recovered_stream_token_does_not_commit() -> None:
    runtime, gateway = _make_runtime()
    store = _b2c2_store(runtime)
    request = _make_request()
    decision = _make_decision()
    decision.memory_recall_required = False
    decision.memory_write_allowed = False
    plan = _make_plan()

    async def primary_failure(*args, **kwargs):
        raise RuntimeError("primary failed")
        yield ChatStreamChunk(type="content", content="never", correlation_id="corr-1")

    recovered = ChatExecutionResult(
        answer="Recovered content",
        metadata=ChatRuntimeMetadata(
            correlation_id=request.context.correlation_id,
            actual_provider="ollama-local",
            actual_model="llama3",
            response_source="model",
            degraded_mode=True,
            fallback_level=1,
        ),
        status=ChatExecutionStatus.DEGRADED,
    )
    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                with patch.object(runtime, "_run_simple_stream", side_effect=primary_failure):
                    with patch("ai_karen_engine.core.runtime.chat_runtime.get_direct_capability_executor") as direct:
                        direct.return_value.can_handle.return_value = False
                        with patch("ai_karen_engine.core.runtime.chat_runtime.build_runtime_fallback", new_callable=AsyncMock, return_value=recovered):
                            with patch.object(runtime, "_persist_transcript", new_callable=AsyncMock) as persist:
                                with patch.object(runtime, "_record_execution_outcome", new_callable=AsyncMock) as outcome:
                                    stream = runtime.execute_stream(request)
                                    assert (await anext(stream)).type == ChatStreamEventType.STATUS
                                    recovered_chunk = await anext(stream)
                                    assert recovered_chunk.type == ChatStreamEventType.CONTENT
                                    assert recovered_chunk.content == "Recovered content"
                                    await stream.aclose()
    rows = store.list_for_tenant(TENANT_ID)
    assert len(rows) == 1
    assert rows[0].execution_status == "cancelled"
    assert rows[0].error_code == "CHAT_REQUEST_CANCELLED"
    assert rows[0].actual_provider is None
    assert gateway.calls == []
    persist.assert_not_awaited()
    outcome.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize("persistence_stage", ["memory", "transcript"])
async def test_b2c2_cancel_during_precommit_persistence_is_terminal(
    streamed: bool, persistence_stage: str,
) -> None:
    """An interrupted write has no completed transcript or learning reward."""
    runtime, gateway = _make_runtime()
    store = _b2c2_store(runtime)
    request = _make_request()
    decision = _make_decision()
    decision.memory_recall_required = False
    decision.memory_write_allowed = persistence_stage == "memory"
    plan = _make_plan()
    persistence_entered = asyncio.Event()

    async def block_before_commit(*args, **kwargs):
        persistence_entered.set()
        await asyncio.Event().wait()

    async def successful_stream(*args, **kwargs):
        yield ChatStreamChunk(
            type="content", content="not committed", correlation_id="corr-1",
        )

    async def consume_stream() -> None:
        async for _ in runtime.execute_stream(request):
            pass

    with ExitStack() as patches:
        patches.enter_context(patch.object(
            runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None,
        ))
        patches.enter_context(patch.object(
            runtime, "_decide", new_callable=AsyncMock, return_value=decision,
        ))
        patches.enter_context(patch.object(
            runtime, "_build_authorized_plan", return_value=plan,
        ))
        patches.enter_context(patch.object(
            runtime, "_grounded_personal_response", return_value=None,
        ))
        patches.enter_context(patch.object(
            runtime, "_is_explicit_save_turn", return_value=False,
        ))
        direct = patches.enter_context(patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_direct_capability_executor",
        ))
        direct.return_value.can_handle.return_value = False
        if streamed:
            patches.enter_context(patch.object(
                runtime, "_run_simple_stream", side_effect=successful_stream,
            ))
        else:
            patches.enter_context(patch.object(
                runtime, "_freeze_persona_snapshot", new_callable=AsyncMock,
            ))
            patches.enter_context(patch.object(
                runtime, "_prepare_conversation_continuation", new_callable=AsyncMock,
            ))
            patches.enter_context(patch.object(
                runtime, "_record_user_behavior_observation", new_callable=AsyncMock,
            ))
            patches.enter_context(patch.object(
                runtime, "_run_simple", new_callable=AsyncMock,
                return_value=("not committed", {
                    "response_source": "model",
                    "actual_provider": "ollama-local",
                    "actual_model": "installed-model",
                }),
            ))

        memory = patches.enter_context(patch.object(
            runtime, "_persist_memory",
            side_effect=block_before_commit if persistence_stage == "memory" else AsyncMock(),
        ))
        transcript = patches.enter_context(patch.object(
            runtime, "_persist_transcript",
            side_effect=block_before_commit if persistence_stage == "transcript" else AsyncMock(),
        ))
        outcome = patches.enter_context(patch.object(
            runtime, "_record_execution_outcome", new_callable=AsyncMock,
        ))

        task = asyncio.create_task(
            consume_stream() if streamed else runtime.execute(request),
        )
        try:
            await asyncio.wait_for(persistence_entered.wait(), timeout=5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    rows = store.list_for_tenant(TENANT_ID)
    assert len(rows) == 1
    assert rows[0].execution_status == "cancelled"
    assert rows[0].error_code == "CHAT_REQUEST_CANCELLED"
    assert rows[0].actual_provider is None
    assert rows[0].response_source is None
    assert gateway.calls == []
    outcome.assert_not_awaited()
    if persistence_stage == "memory":
        memory.assert_awaited_once()
        transcript.assert_not_awaited()
    else:
        transcript.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("committed_status", ["persisted", "already_persisted"])
async def test_b2c2_cancel_after_fallback_transcript_commit_preserves_completion(
    committed_status: str,
) -> None:
    """Later memory cancellation cannot overwrite a durable assistant turn."""
    runtime, gateway = _make_runtime()
    store = _b2c2_store(runtime)
    request = _make_request()
    decision = _make_decision()
    decision.memory_recall_required = False
    decision.memory_write_allowed = True
    plan = _make_plan()
    memory_started = asyncio.Event()
    committed = TranscriptPersistenceResult(
        status=committed_status,
        conversation_id=CONVERSATION_ID,
        user_message_id=USER_MESSAGE_ID,
        assistant_message_id=ASSISTANT_MESSAGE_ID,
        persisted_messages=2 if committed_status == "persisted" else 0,
    )
    recovered = ChatExecutionResult(
        answer="Recovered durable answer",
        metadata=ChatRuntimeMetadata(
            correlation_id=request.context.correlation_id,
            actual_provider="ollama-local",
            actual_model="llama3",
            response_source="fallback_provider_runtime",
            degraded_mode=True,
            fallback_level=1,
        ),
        status=ChatExecutionStatus.DEGRADED,
    )

    async def primary_failure(*args, **kwargs):
        raise RuntimeError("primary failed")

    async def after_commit_memory(*args, **kwargs):
        memory_started.set()
        await asyncio.Event().wait()

    with ExitStack() as patches:
        patches.enter_context(patch.object(
            runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None,
        ))
        patches.enter_context(patch.object(
            runtime, "_freeze_persona_snapshot", new_callable=AsyncMock,
        ))
        patches.enter_context(patch.object(
            runtime, "_prepare_conversation_continuation", new_callable=AsyncMock,
        ))
        patches.enter_context(patch.object(
            runtime, "_decide", new_callable=AsyncMock, return_value=decision,
        ))
        patches.enter_context(patch.object(
            runtime, "_record_user_behavior_observation", new_callable=AsyncMock,
        ))
        patches.enter_context(patch.object(
            runtime, "_build_authorized_plan", return_value=plan,
        ))
        patches.enter_context(patch.object(
            runtime, "_grounded_personal_response", return_value=None,
        ))
        patches.enter_context(patch.object(
            runtime, "_is_explicit_save_turn", return_value=False,
        ))
        direct = patches.enter_context(patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_direct_capability_executor",
        ))
        direct.return_value.can_handle.return_value = False
        patches.enter_context(patch.object(
            runtime, "_run_simple", side_effect=primary_failure,
        ))
        patches.enter_context(patch(
            "ai_karen_engine.core.runtime.chat_runtime.build_runtime_fallback",
            new_callable=AsyncMock, return_value=recovered,
        ))
        transcript = patches.enter_context(patch.object(
            runtime, "_persist_transcript",
            new_callable=AsyncMock, return_value=committed,
        ))
        memory = patches.enter_context(patch.object(
            runtime, "_persist_memory", side_effect=after_commit_memory,
        ))
        outcome = patches.enter_context(patch.object(
            runtime, "_record_execution_outcome", new_callable=AsyncMock,
        ))
        with patch.object(runtime._emitter, "emit") as emitted:
            task = asyncio.create_task(runtime.execute(request))
            try:
                await asyncio.wait_for(memory_started.wait(), timeout=5)
                transcript.assert_awaited_once()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    rows = store.list_for_tenant(TENANT_ID)
    assert len(rows) == 1
    assert rows[0].execution_status == "success"
    assert rows[0].completed_at is not None
    assert rows[0].error_code == "fallback:RuntimeError"
    assert rows[0].actual_provider == "ollama-local"
    assert rows[0].actual_model == "llama3"
    assert rows[0].fallback_level == 1
    assert rows[0].degraded_mode is True
    assert rows[0].response_source == "fallback_provider_runtime"
    assert rows[0].request_id == request.context.request_id
    assert rows[0].tenant_id == TENANT_ID
    assert gateway.calls == []
    memory.assert_awaited_once()
    outcome.assert_not_awaited()
    assert any(
        "REQUEST_CANCELLED" in str(call.args)
        for call in emitted.call_args_list
    ), "post-commit cancellation must still be observable"


@pytest.mark.asyncio
@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize("readback_status", ["already_persisted", "unverified"])
async def test_b2c2_cancel_during_postcommit_session_cleanup_reconciles_truth(
    streamed: bool, readback_status: str,
) -> None:
    """A committed pair has no returned write receipt if cleanup is cancelled."""
    runtime, gateway = _make_runtime()
    store = _b2c2_store(runtime)
    request = _make_request()
    decision = _make_decision()
    decision.memory_recall_required = False
    decision.memory_write_allowed = False
    plan = _make_plan()
    cleanup_entered = asyncio.Event()
    gateway.reconciliation_result = TranscriptPersistenceResult(
        status=readback_status,
        conversation_id=CONVERSATION_ID,
        user_message_id=USER_MESSAGE_ID if readback_status == "already_persisted" else None,
        assistant_message_id=ASSISTANT_MESSAGE_ID if readback_status == "already_persisted" else None,
    )

    async def interrupted_after_commit(*args, **kwargs):
        # Model an underlying transaction which has committed its pair,
        # followed by cancellation while awaited session __aexit__ runs.
        cleanup_entered.set()
        await asyncio.Event().wait()

    async def output_stream(*args, **kwargs):
        kwargs["_meta"].update({
            "response_source": "provider_runtime",
            "actual_provider": "ollama-local",
            "actual_model": "installed-model",
        })
        yield ChatStreamChunk(
            type="content", content="Durable answer", correlation_id="corr-1",
        )

    async def consume_stream() -> None:
        async for _ in runtime.execute_stream(request):
            pass

    with ExitStack() as patches:
        patches.enter_context(patch.object(
            runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None,
        ))
        patches.enter_context(patch.object(
            runtime, "_decide", new_callable=AsyncMock, return_value=decision,
        ))
        patches.enter_context(patch.object(
            runtime, "_build_authorized_plan", return_value=plan,
        ))
        patches.enter_context(patch.object(
            runtime, "_grounded_personal_response", return_value=None,
        ))
        patches.enter_context(patch.object(
            runtime, "_is_explicit_save_turn", return_value=False,
        ))
        direct = patches.enter_context(patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_direct_capability_executor",
        ))
        direct.return_value.can_handle.return_value = False
        if streamed:
            patches.enter_context(patch.object(
                runtime, "_run_simple_stream", side_effect=output_stream,
            ))
        else:
            patches.enter_context(patch.object(
                runtime, "_freeze_persona_snapshot", new_callable=AsyncMock,
            ))
            patches.enter_context(patch.object(
                runtime, "_prepare_conversation_continuation", new_callable=AsyncMock,
            ))
            patches.enter_context(patch.object(
                runtime, "_record_user_behavior_observation", new_callable=AsyncMock,
            ))
            patches.enter_context(patch.object(
                runtime, "_run_simple", new_callable=AsyncMock,
                return_value=("Durable answer", {
                    "response_source": "provider_runtime",
                    "actual_provider": "ollama-local",
                    "actual_model": "installed-model",
                }),
            ))
        transcript = patches.enter_context(patch.object(
            runtime, "_persist_transcript", side_effect=interrupted_after_commit,
        ))
        outcome = patches.enter_context(patch.object(
            runtime, "_record_execution_outcome", new_callable=AsyncMock,
        ))
        task = asyncio.create_task(
            consume_stream() if streamed else runtime.execute(request),
        )
        try:
            await asyncio.wait_for(cleanup_entered.wait(), timeout=5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert transcript.await_count == 1
    assert len(gateway.reconciliation_calls) == 1
    verified = gateway.reconciliation_calls[0]
    assert verified["assistant_text"] == "Durable answer"
    assert verified["user_text"] == "hello"
    assert verified["context"] is request.context
    rows = store.list_for_tenant(TENANT_ID)
    assert len(rows) == 1
    if readback_status == "already_persisted":
        assert rows[0].execution_status == "success"
        assert rows[0].actual_provider == "ollama-local"
        assert rows[0].actual_model == "installed-model"
        assert rows[0].error_code is None
    else:
        assert rows[0].execution_status not in {"success", "cancelled"}
        assert rows[0].error_code != "CHAT_REQUEST_CANCELLED"
    outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_b2c2_leased_stream_postcommit_memory_cancellation_preserves_turn() -> None:
    """An atomic run+transcript commit survives later memory cancellation."""
    runtime, gateway = _make_runtime()
    store = _b2c2_store(runtime)
    request = _make_request()
    request.runtime_run_lease = ChatRunLease(
        execution_id="55555555-5555-5555-5555-555555555555",
        lease_token="66666666-6666-6666-6666-666666666666",
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
        transport_run_id="run-leased",
        request_id=request.context.request_id,
        correlation_id=request.context.correlation_id,
    )
    decision = _make_decision()
    decision.memory_recall_required = False
    decision.memory_write_allowed = True
    plan = _make_plan()
    memory_entered = asyncio.Event()

    async def committed_stream(*args, **kwargs):
        kwargs["_meta"].update({
            "response_source": "provider_runtime",
            "actual_provider": "ollama-local",
            "actual_model": "installed-model",
        })
        yield ChatStreamChunk(
            type="content", content="Committed streamed answer",
            correlation_id="corr-1",
        )

    async def interrupted_memory(*args, **kwargs):
        memory_entered.set()
        await asyncio.Event().wait()

    async def consume() -> None:
        async for _ in runtime.execute_stream(request):
            pass

    with ExitStack() as patches:
        patches.enter_context(patch.object(
            runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None,
        ))
        patches.enter_context(patch.object(
            runtime, "_decide", new_callable=AsyncMock, return_value=decision,
        ))
        patches.enter_context(patch.object(
            runtime, "_build_authorized_plan", return_value=plan,
        ))
        patches.enter_context(patch.object(
            runtime, "_grounded_personal_response", return_value=None,
        ))
        patches.enter_context(patch.object(
            runtime, "_is_explicit_save_turn", return_value=False,
        ))
        direct = patches.enter_context(patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_direct_capability_executor",
        ))
        direct.return_value.can_handle.return_value = False
        patches.enter_context(patch.object(
            runtime, "_run_simple_stream", side_effect=committed_stream,
        ))
        transcript = patches.enter_context(patch.object(
            runtime, "_persist_transcript", new_callable=AsyncMock,
            return_value=TranscriptPersistenceResult(
                status="persisted", conversation_id=CONVERSATION_ID,
                user_message_id=USER_MESSAGE_ID,
                assistant_message_id=ASSISTANT_MESSAGE_ID,
                persisted_messages=2,
            ),
        ))
        memory = patches.enter_context(patch.object(
            runtime, "_persist_memory", side_effect=interrupted_memory,
        ))
        outcome = patches.enter_context(patch.object(
            runtime, "_record_execution_outcome", new_callable=AsyncMock,
        ))
        task = asyncio.create_task(consume())
        try:
            await asyncio.wait_for(memory_entered.wait(), timeout=5)
            transcript.assert_awaited_once()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    assert len(store.list_for_tenant(TENANT_ID)) == 1
    row = store.list_for_tenant(TENANT_ID)[0]
    assert row.execution_status == "success"
    assert row.error_code is None
    assert row.actual_provider == "ollama-local"
    assert row.actual_model == "installed-model"
    assert row.tenant_id == TENANT_ID
    assert row.user_id == USER_ID
    assert row.request_id == request.context.request_id
    assert row.response_source == "provider_runtime"
    assert gateway.reconciliation_calls == []
    memory.assert_awaited_once()
    outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoked_memory_between_stream_deltas_stops_publication_and_persistence():
    """A queued second token cannot bypass the canonical outer stream guard."""
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()
    checks = 0
    memory_persist = AsyncMock()
    generator_closed = False

    async def revoke_after_first_chunk(_request, _decision):
        nonlocal checks
        checks += 1
        if checks >= 2:
            raise RuntimeError("memory_source_revoked_or_unverifiable")

    async def fake_stream(*args, **kwargs):
        nonlocal generator_closed
        try:
            for chunk in _fake_stream_chunks():
                yield chunk
        finally:
            generator_closed = True

    with patch.object(
        ChatRuntime,
        "_authorize_selected_memory_before_generation",
        side_effect=revoke_after_first_chunk,
    ):
        chunks = await _collect_stream(
            runtime, request, decision, plan, fake_stream,
            persist_memory=memory_persist,
        )

    published = [chunk.content for chunk in chunks if chunk.type == "content"]
    assert published == ["Hello"]
    assert generator_closed is True
    assert any(chunk.type == "error" for chunk in chunks)
    assert not gateway.calls
    memory_persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_revocation_after_final_stream_delta_blocks_transcript():
    """No completed stream may turn into durable success after late revocation."""
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()
    checks = 0
    memory_persist = AsyncMock()

    async def revoke_at_finality(_request, _decision):
        nonlocal checks
        checks += 1
        if checks >= 3:
            raise RuntimeError("memory_source_revoked_or_unverifiable")

    async def fake_stream(*args, **kwargs):
        for chunk in _fake_stream_chunks():
            yield chunk

    with patch.object(
        ChatRuntime,
        "_authorize_selected_memory_before_generation",
        side_effect=revoke_at_finality,
    ):
        chunks = await _collect_stream(
            runtime, request, decision, plan, fake_stream,
            persist_memory=memory_persist,
        )

    assert [chunk.content for chunk in chunks if chunk.type == "content"] == [
        "Hello", " world",
    ]
    assert any(chunk.type == "error" for chunk in chunks)
    assert not gateway.calls
    memory_persist.assert_not_awaited()


def test_post_provider_and_finality_source_fences_are_runtime_owned():
    from pathlib import Path

    runtime_source = (
        Path(__file__).resolve().parents[3]
        / "src/ai_karen_engine/core/runtime/chat_runtime.py"
    ).read_text(encoding="utf-8")
    direct = runtime_source.split("    async def _run_simple(", 1)[1].split(
        "    async def _run_simple_stream(", 1
    )[0]
    assert direct.index("result = await gateway.generate(task)") < direct.index(
        "await ChatRuntime._authorize_selected_memory_before_generation(",
        direct.index("result = await gateway.generate(task)"),
    )
    outer = runtime_source.split("    async def execute_stream(", 1)[1].split(
        "    async def _run_simple(", 1
    )[0]
    assert outer.index('if chunk.type == "content":') < outer.index(
        "await ChatRuntime._authorize_selected_memory_before_generation(",
        outer.index('if chunk.type == "content":'),
    )


@pytest.mark.asyncio
async def test_reasoning_wrapper_close_cancels_real_nested_provider_worker():
    """Outer reasoning closure must not defer the inner provider task's finally."""
    runtime, _ = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()
    meter = ExecutionBudgetMeter(plan.budget)
    meter.start()
    cancelled = asyncio.Event()
    blocked = asyncio.Event()

    async def provider(*args, token_sink=None, **kwargs):
        assert token_sink is not None
        await token_sink("first")
        try:
            await blocked.wait()
        finally:
            cancelled.set()
        return ("first", {})

    with patch.object(
        runtime, "_run_reasoning", new_callable=AsyncMock,
        return_value=("reasoning", {"reasoning_status": "completed"}),
    ):
        with patch.object(
            runtime, "_should_synthesize_after_reasoning", return_value=True,
        ):
            with patch.object(runtime, "_run_simple", side_effect=provider):
                stream = runtime._run_reasoning_stream(
                    request, decision, plan, meter,
                )
                first = await asyncio.wait_for(anext(stream), timeout=5)
                assert first.content == "first"
                await asyncio.wait_for(stream.aclose(), timeout=5)
    await asyncio.wait_for(cancelled.wait(), timeout=5)


@pytest.mark.asyncio
async def test_revocation_during_nonstream_memory_persistence_returns_denial():
    """A late source change must not escape as an uncaught HTTP 500."""
    runtime, gateway = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    decision.memory_recall_required = False
    plan = _make_plan()
    revoked = False
    persist_calls = 0

    async def persist_then_revoke(*args, **kwargs):
        nonlocal revoked, persist_calls
        persist_calls += 1
        revoked = True

    async def check_source(*args, **kwargs):
        if revoked:
            raise RuntimeError("memory_source_revoked_or_unverifiable")

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_freeze_persona_snapshot", new_callable=AsyncMock):
            with patch.object(runtime, "_prepare_conversation_continuation", new_callable=AsyncMock):
                with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
                    with patch.object(runtime, "_record_user_behavior_observation", new_callable=AsyncMock):
                        with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                            with patch.object(runtime, "_grounded_personal_response", return_value=None):
                                with patch.object(runtime, "_is_explicit_save_turn", return_value=False):
                                    with patch("ai_karen_engine.core.runtime.chat_runtime.get_direct_capability_executor") as direct:
                                        direct.return_value.can_handle.return_value = False
                                        with patch.object(
                                            runtime, "_run_simple", new_callable=AsyncMock,
                                            return_value=("generated", {"execution_spans": []}),
                                        ):
                                            with patch.object(runtime, "_persist_memory", side_effect=persist_then_revoke):
                                                with patch.object(
                                                    ChatRuntime, "_authorize_selected_memory_before_generation",
                                                    side_effect=check_source,
                                                ):
                                                    result = await runtime.execute(request)
    assert persist_calls == 1
    assert result.status == ChatExecutionStatus.ERROR
    assert result.answer == ""
    assert result.metadata.extra["error_code"] == "CHAT_MEMORY_SOURCE_REVOKED"
    assert not gateway.calls


@pytest.mark.asyncio
async def test_graph_wrapper_close_propagates_to_workflow_stream():
    runtime, _ = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()
    meter = ExecutionBudgetMeter(plan.budget)
    meter.start()
    closed = asyncio.Event()

    async def workflow_stream(*args, **kwargs):
        try:
            yield ChatStreamChunk(
                type="content", content="graph delta", correlation_id="corr-1",
            )
            await asyncio.Event().wait()
        finally:
            closed.set()

    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_workflow_runtime"
    ) as workflow:
        workflow.return_value.stream.side_effect = workflow_stream
        stream = runtime._run_graph_stream(
            request, decision, plan, meter,
        )
        first = await asyncio.wait_for(anext(stream), timeout=5)
        assert first.content == "graph delta"
        await asyncio.wait_for(stream.aclose(), timeout=5)
    assert closed.is_set()


@pytest.mark.asyncio
async def test_cancel_during_stream_final_source_check_records_terminal():
    runtime, _ = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()
    entered = asyncio.Event()
    blocked = asyncio.Event()
    checks = 0

    async def source_check(*args, **kwargs):
        nonlocal checks
        checks += 1
        if checks >= 2:
            entered.set()
            await blocked.wait()

    async def provider_stream(*args, **kwargs):
        yield ChatStreamChunk(
            type="content", content="partial", correlation_id="corr-1",
        )

    with patch.object(
        ChatRuntime, "_authorize_selected_memory_before_generation",
        side_effect=source_check,
    ):
        with patch.object(
            runtime, "_observe_request_cancellation", new_callable=AsyncMock,
        ) as observer:
            task = asyncio.create_task(_collect_stream(
                runtime, request, decision, plan, provider_stream,
            ))
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            finally:
                if not task.done():
                    task.cancel()
    observer.assert_awaited()


@pytest.mark.asyncio
async def test_cancel_during_nonstream_source_finality_records_terminal():
    runtime, _ = _make_runtime()
    request = _make_request()
    decision = _make_decision()
    decision.memory_recall_required = False
    plan = _make_plan()
    entered = asyncio.Event()
    blocked = asyncio.Event()

    async def source_check(*args, **kwargs):
        entered.set()
        await blocked.wait()

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_freeze_persona_snapshot", new_callable=AsyncMock):
            with patch.object(runtime, "_prepare_conversation_continuation", new_callable=AsyncMock):
                with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
                    with patch.object(runtime, "_record_user_behavior_observation", new_callable=AsyncMock):
                        with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                            with patch.object(runtime, "_grounded_personal_response", return_value=None):
                                with patch.object(runtime, "_is_explicit_save_turn", return_value=False):
                                    with patch("ai_karen_engine.core.runtime.chat_runtime.get_direct_capability_executor") as direct:
                                        direct.return_value.can_handle.return_value = False
                                        with patch.object(
                                            runtime, "_run_simple", new_callable=AsyncMock,
                                            return_value=("generated", {"execution_spans": []}),
                                        ):
                                            with patch.object(
                                                ChatRuntime, "_authorize_selected_memory_before_generation",
                                                side_effect=source_check,
                                            ):
                                                with patch.object(
                                                    runtime, "_observe_request_cancellation",
                                                    new_callable=AsyncMock,
                                                ) as observer:
                                                    task = asyncio.create_task(runtime.execute(request))
                                                    try:
                                                        await asyncio.wait_for(entered.wait(), timeout=5)
                                                        task.cancel()
                                                        with pytest.raises(asyncio.CancelledError):
                                                            await task
                                                    finally:
                                                        if not task.done():
                                                            task.cancel()
    observer.assert_awaited()
