import asyncio
import datetime
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatStreamChunk,
    ChatStreamEventType,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionTopology,
)


def _make_request() -> ChatExecutionRequest:
    ctx = ChatExecutionContext(
        user_id="user-1",
        tenant_id="default",
        session_id="session-1",
        conversation_id="conv-1",
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
    decision.time_budget_ms = 60000
    decision.max_steps = 5
    decision.token_budget = 4096
    decision.reasoning_depth = "standard"
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
    return decision


def _make_plan() -> AuthorizedExecutionPlan:
    return AuthorizedExecutionPlan(
        execution_id="exec-req-1",
        policy_decision_id="policy-1",
        topology=ExecutionTopology.DIRECT,
        allowed_capabilities=[],
        allowed_tools=[],
        allowed_plugins=[],
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


def _fake_stream_chunks() -> list:
    return [
        ChatStreamChunk(type="content", content="Hello", correlation_id="corr-1"),
        ChatStreamChunk(type="content", content=" world", correlation_id="corr-1"),
    ]


@pytest.mark.asyncio
async def test_execute_stream_assigns_canonical_sequence_and_ids():
    runtime = ChatRuntime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    chunks = []

    async def fake_stream(*args, **kwargs):
        for chunk in _fake_stream_chunks():
            yield chunk

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                with patch.object(runtime, "_recall_memory", new_callable=AsyncMock, return_value={}):
                    with patch.object(runtime, "_run_simple_stream", side_effect=fake_stream):
                        with patch.object(runtime, "_persist_memory", new_callable=AsyncMock):
                            with patch.object(runtime, "_record_trajectory_completion"):
                                with patch.object(runtime, "_record_execution_outcome"):
                                    with patch.object(runtime._emitter, "emit"):
                                        async for chunk in runtime.execute_stream(request):
                                            chunks.append(chunk)

    assert len(chunks) == 3  # 2 content + 1 complete
    assert chunks[0].sequence == 0
    assert chunks[1].sequence == 1
    assert chunks[2].sequence == 2

    event_ids = [c.event_id for c in chunks]
    assert len(event_ids) == len(set(event_ids)), "event_id must be unique"

    for chunk in chunks:
        assert chunk.correlation_id == "corr-1"
        assert chunk.request_id == "req-1"
        assert chunk.response_id == "req-1"
        assert chunk.conversation_id == "conv-1"
        assert isinstance(chunk.timestamp, datetime.datetime)


@pytest.mark.asyncio
async def test_execute_stream_emits_exactly_one_complete_on_success():
    runtime = ChatRuntime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="content", content="hi", correlation_id="corr-1")

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                with patch.object(runtime, "_recall_memory", new_callable=AsyncMock, return_value={}):
                    with patch.object(runtime, "_run_simple_stream", side_effect=fake_stream):
                        with patch.object(runtime, "_persist_memory", new_callable=AsyncMock):
                            with patch.object(runtime, "_record_trajectory_completion"):
                                with patch.object(runtime, "_record_execution_outcome"):
                                    with patch.object(runtime._emitter, "emit"):
                                        chunks = [
                                            chunk
                                            async for chunk in runtime.execute_stream(request)
                                        ]

    complete_chunks = [c for c in chunks if c.type == ChatStreamEventType.COMPLETE]
    assert len(complete_chunks) == 1


@pytest.mark.asyncio
async def test_execute_stream_emits_complete_on_generation_failure():
    runtime = ChatRuntime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="error", content="boom", correlation_id="corr-1")

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                with patch.object(runtime, "_recall_memory", new_callable=AsyncMock, return_value={}):
                    with patch.object(runtime, "_run_simple_stream", side_effect=fake_stream):
                        with patch.object(runtime, "_persist_memory", new_callable=AsyncMock):
                            with patch.object(runtime, "_record_trajectory_completion"):
                                with patch.object(runtime, "_record_execution_outcome"):
                                    with patch.object(runtime._emitter, "emit"):
                                        chunks = [
                                            chunk
                                            async for chunk in runtime.execute_stream(request)
                                        ]

    assert chunks[0].type == ChatStreamEventType.ERROR
    assert chunks[1].type == ChatStreamEventType.COMPLETE
    assert len([c for c in chunks if c.type == ChatStreamEventType.COMPLETE]) == 1


@pytest.mark.asyncio
async def test_execute_stream_handles_persistence_failure_as_degraded():
    runtime = ChatRuntime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="content", content="hi", correlation_id="corr-1")

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                with patch.object(runtime, "_recall_memory", new_callable=AsyncMock, return_value={"memory_recall_required": True, "memory_write_allowed": True}):
                    with patch.object(runtime, "_run_simple_stream", side_effect=fake_stream):
                        def fail_persistence(request, text, meta, plan):
                            meta["memory_persistence_status"] = "failed"
                            raise RuntimeError("db down")
                        with patch.object(runtime, "_persist_memory", new_callable=AsyncMock, side_effect=fail_persistence):
                            with patch.object(runtime, "_record_trajectory_completion"):
                                with patch.object(runtime, "_record_execution_outcome"):
                                    with patch.object(runtime._emitter, "emit"):
                                        chunks = [
                                            chunk
                                            async for chunk in runtime.execute_stream(request)
                                        ]

    complete_chunks = [c for c in chunks if c.type == ChatStreamEventType.COMPLETE]
    assert len(complete_chunks) == 1
    terminal_meta = complete_chunks[0].metadata
    assert terminal_meta.get("status") == "degraded"
    assert terminal_meta.get("memory_persistence_status") == "failed"
    assert terminal_meta.get("degradation_reason") == "memory_persistence_failed"


@pytest.mark.asyncio
async def test_execute_stream_does_not_yield_complete_on_cancelled_error():
    runtime = ChatRuntime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="content", content="hi", correlation_id="corr-1")
        raise asyncio.CancelledError()

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                with patch.object(runtime, "_recall_memory", new_callable=AsyncMock, return_value={}):
                    with patch.object(runtime, "_run_simple_stream", side_effect=fake_stream):
                        with patch.object(runtime, "_persist_memory", new_callable=AsyncMock):
                            with patch.object(runtime, "_record_trajectory_completion"):
                                with patch.object(runtime, "_record_execution_outcome"):
                                    with patch.object(runtime._emitter, "emit"):
                                        with pytest.raises(asyncio.CancelledError):
                                            async for _ in runtime.execute_stream(request):
                                                pass


@pytest.mark.asyncio
async def test_execute_stream_terminal_complete_metadata_is_complete():
    runtime = ChatRuntime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="content", content="hi", correlation_id="corr-1")

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                with patch.object(runtime, "_recall_memory", new_callable=AsyncMock, return_value={}):
                    with patch.object(runtime, "_run_simple_stream", side_effect=fake_stream):
                        with patch.object(runtime, "_persist_memory", new_callable=AsyncMock):
                            with patch.object(runtime, "_record_trajectory_completion"):
                                with patch.object(runtime, "_record_execution_outcome"):
                                    with patch.object(runtime._emitter, "emit"):
                                        chunks = [
                                            chunk
                                            async for chunk in runtime.execute_stream(request)
                                        ]

    complete_chunks = [c for c in chunks if c.type == ChatStreamEventType.COMPLETE]
    assert len(complete_chunks) == 1
    meta = complete_chunks[0].metadata
    expected_keys = [
        "correlation_id",
        "request_id",
        "response_id",
        "conversation_id",
        "assistant_message_id",
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
        "status",
    ]
    for key in expected_keys:
        assert key in meta, f"terminal metadata missing {key}"


@pytest.mark.asyncio
async def test_execute_stream_ignores_inner_complete_events():
    runtime = ChatRuntime()
    request = _make_request()
    decision = _make_decision()
    plan = _make_plan()

    async def fake_stream(*args, **kwargs):
        yield ChatStreamChunk(type="content", content="hi", correlation_id="corr-1")
        yield ChatStreamChunk(type="complete", content="", correlation_id="corr-1")
        yield ChatStreamChunk(type="content", content=" there", correlation_id="corr-1")

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None):
        with patch.object(runtime, "_decide", new_callable=AsyncMock, return_value=decision):
            with patch.object(runtime, "_build_authorized_plan", return_value=plan):
                with patch.object(runtime, "_recall_memory", new_callable=AsyncMock, return_value={}):
                    with patch.object(runtime, "_run_simple_stream", side_effect=fake_stream):
                        with patch.object(runtime, "_persist_memory", new_callable=AsyncMock):
                            with patch.object(runtime, "_record_trajectory_completion"):
                                with patch.object(runtime, "_record_execution_outcome"):
                                    with patch.object(runtime._emitter, "emit"):
                                        chunks = [
                                            chunk
                                            async for chunk in runtime.execute_stream(request)
                                        ]

    complete_chunks = [c for c in chunks if c.type == ChatStreamEventType.COMPLETE]
    assert len(complete_chunks) == 1
    content_chunks = [c for c in chunks if c.type == ChatStreamEventType.CONTENT]
    assert len(content_chunks) == 2


@pytest.mark.asyncio
async def test_execute_stream_gate_emits_error_and_complete():
    runtime = ChatRuntime()
    request = _make_request()
    gate = MagicMock()
    gate.mode = "maintenance"
    gate.message = "Service unavailable"

    with patch.object(runtime, "_resolve_gate", new_callable=AsyncMock, return_value=gate):
        with patch.object(runtime._emitter, "emit"):
            chunks = [
                chunk
                async for chunk in runtime.execute_stream(request)
            ]

    assert len(chunks) == 2
    assert chunks[0].type == ChatStreamEventType.ERROR
    assert chunks[1].type == ChatStreamEventType.COMPLETE
    assert len([c for c in chunks if c.type == ChatStreamEventType.COMPLETE]) == 1
