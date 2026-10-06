import asyncio
import datetime
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatExecutionStatus,
    ChatStreamChunk,
    ChatStreamEventType,
)
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    TranscriptPersistenceResult,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
    ApprovalRequiredResponse,
)
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
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

    async def persist_completed_turn(
        self,
        context: ChatExecutionContext,
        *,
        user_text: str,
        assistant_text: str,
        response_metadata: Optional[Dict[str, Any]] = None,
    ) -> TranscriptPersistenceResult:
        self.calls.append(
            {
                "context": context,
                "user_text": user_text,
                "assistant_text": assistant_text,
                "response_metadata": dict(response_metadata or {}),
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
    )
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "hello"}],
        context=ctx,
        preferred_provider="ollama",
        preferred_model="llama3",
    )


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
        execution_id="exec-req-1",
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
) -> list[ChatStreamChunk]:
    memory_persist = persist_memory or AsyncMock()
    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                with patch.object(
                    runtime,
                    "_consume_resolved_memory",
                    new_callable=AsyncMock,
                    return_value={
                        "memory_recall_status": "success",
                        "memory_recall_count": 0,
                        "memory_persistence_status": "skipped",
                    },
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
