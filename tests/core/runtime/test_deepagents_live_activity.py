"""Real Medusa observations are forwarded without inventing agent progress."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.agent_medusa.contracts.events import AgentEvent, AgentEventType
from ai_karen_engine.agent_medusa.contracts.runtime_response import (
    ResponseStatus,
    RuntimeResponse,
)
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatStreamEventType,
)
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionTopology,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.workflow_runtime import WorkflowRuntime


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    import ai_karen_engine.config.agent_medusa as config

    monkeypatch.setattr(
        config,
        "get_agent_medusa_runtime_settings",
        lambda: SimpleNamespace(deepagents_research_enabled=True),
    )


def _request():
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "Research the request"}],
        context=ChatExecutionContext(
            user_id="u-1", tenant_id="t-1", session_id="s-1",
            conversation_id="c-1", request_id="req-1", correlation_id="corr-1",
        ),
    )


def _decision():
    return ExecutionDecision(
        topology=ExecutionTopology.MULTI_AGENT,
        requires_agent_delegation=True,
    )


def _plan():
    return AuthorizedExecutionPlan(
        execution_id="req-1", policy_decision_id="policy-1",
        authorized_user_id="u-1", authorized_tenant_id="t-1",
        authorized_session_id="s-1", topology=ExecutionTopology.MULTI_AGENT,
        allowed_agents=["researcher"], allowed_tools=["web_search"],
    )


def _event(kind, *, correlation_id="corr-1", **metadata):
    return AgentEvent(
        type=kind, agent_id="researcher", message="internal sensitive description",
        correlation_id=correlation_id,
        metadata={"step_id": "step-1", "secret": "do-not-expose", **metadata},
    )


def test_medusa_agent_projection_contains_only_authorized_status_and_identity():
    rt = WorkflowRuntime()
    emitted = rt._project_medusa_event(
        _event(AgentEventType.AGENT_STARTED), correlation_id="corr-1",
    )
    assert emitted.type == ChatStreamEventType.AGENT_STEP
    assert emitted.metadata["event_type"] == "agent_step_started"
    assert emitted.metadata["status"] == "running"
    assert emitted.metadata["step_id"] == "step-1"
    assert emitted.metadata["agent_id"] == "researcher"
    assert emitted.content == "Agent step running."
    assert "secret" not in str(emitted)
    assert "internal sensitive" not in str(emitted)

    finished = rt._project_medusa_event(
        _event(AgentEventType.AGENT_COMPLETED), correlation_id="corr-1",
    )
    failed = rt._project_medusa_event(
        _event(AgentEventType.AGENT_FAILED), correlation_id="corr-1",
    )
    assert finished.metadata["status"] == "completed"
    assert failed.metadata["status"] == "failed"


def test_medusa_tool_projection_preserves_actual_ids_without_tool_arguments():
    rt = WorkflowRuntime()
    begin = rt._project_medusa_event(
        _event(
            AgentEventType.TOOL_CALL_STARTED,
            tool="web_search", tool_call_id="call-1",
            args={"api_key": "never-expose"},
        ),
        correlation_id="corr-1",
    )
    done = rt._project_medusa_event(
        _event(
            AgentEventType.TOOL_CALL_COMPLETED,
            tool="web_search", tool_call_id="call-1",
            result={"secret": "never-expose"},
        ),
        correlation_id="corr-1",
    )
    assert begin.type == ChatStreamEventType.TOOL
    assert begin.metadata["phase"] == "started"
    assert done.metadata["phase"] == "completed"
    assert begin.metadata["tool_call_id"] == done.metadata["tool_call_id"]
    assert "never-expose" not in str(begin) + str(done)


def test_medusa_projection_rejects_cross_run_events_and_unidentified_tools():
    rt = WorkflowRuntime()
    assert rt._project_medusa_event(
        _event(AgentEventType.AGENT_STARTED, correlation_id="other-run"),
        correlation_id="corr-1",
    ) is None
    assert rt._project_medusa_event(
        _event(AgentEventType.TOOL_CALL_STARTED, tool="web_search"),
        correlation_id="corr-1",
    ) is None
    assert rt._project_medusa_event(
        _event(AgentEventType.PLAN_CREATED),
        correlation_id="corr-1",
    ) is None


@pytest.mark.asyncio
async def test_deepagents_stream_exposes_real_steps_and_tool_boundaries(monkeypatch):
    class ObservedCoordinator:
        def attach_sink(self, sink):
            self._sink = sink

        async def handle_request(self, request):
            assert request.tenant_id == "t-1"
            self._sink(_event(AgentEventType.AGENT_STARTED))
            await asyncio.sleep(0)
            self._sink(_event(
                AgentEventType.TOOL_CALL_STARTED,
                tool="web_search", tool_call_id="call-1",
            ))
            self._sink(_event(
                AgentEventType.TOOL_CALL_COMPLETED,
                tool="web_search", tool_call_id="call-1",
            ))
            self._sink(_event(AgentEventType.AGENT_COMPLETED))
            return RuntimeResponse(
                request_id="req-1", status=ResponseStatus.SUCCESS,
                content="Verified agent answer",
            )

    monkeypatch.setattr(
        "ai_karen_engine.agent_medusa.coordinator.medusa_coordinator."
        "MedusaCoordinator",
        ObservedCoordinator,
    )
    runtime = WorkflowRuntime()
    runtime._get_orchestrator = AsyncMock(
        side_effect=AssertionError("Outer LangGraph must not run")
    )
    chunks = [c async for c in runtime.stream(_request(), _decision(), _plan())]
    assert [c.type for c in chunks] == [
        ChatStreamEventType.STATUS,
        ChatStreamEventType.AGENT_STEP,
        ChatStreamEventType.TOOL,
        ChatStreamEventType.TOOL,
        ChatStreamEventType.AGENT_STEP,
        ChatStreamEventType.CONTENT,
    ]
    assert [c.metadata.get("status") for c in chunks if c.type == ChatStreamEventType.AGENT_STEP] == [
        "running", "completed"
    ]
    assert chunks[-1].content == "Verified agent answer"
    assert all(c.correlation_id == "corr-1" for c in chunks)


@pytest.mark.asyncio
async def test_closing_deepagents_stream_cancels_its_real_worker(monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class HangingCoordinator:
        def attach_sink(self, sink):
            self._sink = sink

        async def handle_request(self, _request):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    monkeypatch.setattr(
        "ai_karen_engine.agent_medusa.coordinator.medusa_coordinator."
        "MedusaCoordinator",
        HangingCoordinator,
    )
    stream = WorkflowRuntime().stream(_request(), _decision(), _plan())
    first = await anext(stream)
    assert first.type == ChatStreamEventType.STATUS
    await asyncio.wait_for(started.wait(), 2.0)
    await stream.aclose()
    await asyncio.wait_for(cancelled.wait(), 2.0)


@pytest.mark.asyncio
async def test_deepagents_stream_reports_failure_without_fabricated_content(monkeypatch):
    class FailingCoordinator:
        def attach_sink(self, sink):
            self._sink = sink

        async def handle_request(self, _request):
            self._sink(_event(AgentEventType.AGENT_STARTED))
            raise RuntimeError("secret backend detail")

    monkeypatch.setattr(
        "ai_karen_engine.agent_medusa.coordinator.medusa_coordinator."
        "MedusaCoordinator",
        FailingCoordinator,
    )
    chunks = [
        c async for c in WorkflowRuntime().stream(_request(), _decision(), _plan())
    ]
    assert chunks[-1].type == ChatStreamEventType.ERROR
    assert not any(c.type == ChatStreamEventType.CONTENT for c in chunks)
    assert "secret backend detail" not in str(chunks)


def test_deepagents_real_planning_and_delegation_events_project_to_agent_activity():
    rt = WorkflowRuntime()
    for kind, activity_kind in (
        (AgentEventType.PLAN_UPDATED, "plan"),
        (AgentEventType.REASONING_STEP, "subagent"),
    ):
        started = rt._project_medusa_event(
            _event(
                kind, step_id="deepagents-real-123", source="deepagents",
                activity_kind=activity_kind, status="running",
                subagent_run_id="real-123" if activity_kind == "subagent" else "",
                private_tool_input={"token": "never-forward"},
            ),
            correlation_id="corr-1",
        )
        completed = rt._project_medusa_event(
            _event(
                kind, step_id="deepagents-real-123", source="deepagents",
                activity_kind=activity_kind, status="completed",
                subagent_run_id="real-123" if activity_kind == "subagent" else "",
            ),
            correlation_id="corr-1",
        )
        assert started.type == ChatStreamEventType.AGENT_STEP
        assert started.metadata["status"] == "running"
        assert started.metadata["source"] == "deepagents"
        assert started.metadata["activity_kind"] == activity_kind
        assert started.metadata["step_id"] == completed.metadata["step_id"]
        assert completed.metadata["status"] == "completed"
        assert "never-forward" not in str(started) + str(completed)


def test_deepagents_progress_requires_actual_sdk_source_and_subagent_identity():
    rt = WorkflowRuntime()
    assert rt._project_medusa_event(
        _event(
            AgentEventType.REASONING_STEP,
            step_id="deepagents-unproven", status="running",
            activity_kind="subagent", subagent_run_id="real-123",
        ), correlation_id="corr-1",
    ) is None
    assert rt._project_medusa_event(
        _event(
            AgentEventType.PLAN_UPDATED,
            step_id="deepagents-unproven", status="running",
            activity_kind="plan", source="different-engine",
        ), correlation_id="corr-1",
    ) is None
    assert rt._project_medusa_event(
        _event(
            AgentEventType.REASONING_STEP,
            step_id="deepagents-unproven", status="running",
            activity_kind="subagent", source="deepagents",
        ), correlation_id="corr-1",
    ) is None


def test_verified_postgres_checkpoint_is_status_only_never_resume_claim():
    rt = WorkflowRuntime()
    event = rt._project_medusa_event(
        _event(
            AgentEventType.CHECKPOINT_PERSISTED,
            step_id="step-1", source="deepagents",
            checkpoint_verified=True, resumable=False,
            raw_checkpoint={"secret": "private-bytes"},
        ),
        correlation_id="corr-1",
    )
    assert event.type == ChatStreamEventType.STATUS
    assert event.metadata["checkpoint_verified"] is True
    assert event.metadata["resumable"] is False
    assert event.metadata["step_id"] == "step-1"
    assert "private-bytes" not in str(event)

    unsafe = rt._project_medusa_event(
        _event(
            AgentEventType.CHECKPOINT_PERSISTED,
            step_id="step-1", source="deepagents",
            checkpoint_verified=False, resumable=True,
        ),
        correlation_id="corr-1",
    )
    assert unsafe is None
