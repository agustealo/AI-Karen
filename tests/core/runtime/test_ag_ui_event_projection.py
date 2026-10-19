"""Regression proof for AG-UI projections over canonical chat events."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.ag_ui_event_projection import AGUIEventProjection


def chunk(kind: str, content: str = "", **metadata):
    return SimpleNamespace(type=kind, content=content, metadata=metadata)


def test_stream_lifecycle_preserves_text_and_requires_real_completion():
    p = AGUIEventProjection(thread_id="tenant-thread", run_id="run-1")
    assert p.begin() == {
        "type": "RUN_STARTED", "threadId": "tenant-thread", "runId": "run-1"
    }
    first = p.project(chunk("content", "Hello "))
    second = p.project(chunk("content", "world"))
    completed = p.project(chunk("complete"))
    assert [event["type"] for event in first] == [
        "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT"
    ]
    assert first[1]["delta"] == "Hello "
    assert [event["type"] for event in second] == ["TEXT_MESSAGE_CONTENT"]
    assert second[0]["delta"] == "world"
    assert [event["type"] for event in completed] == [
        "TEXT_MESSAGE_END", "RUN_FINISHED"
    ]
    assert p.terminal
    assert p.fail_incomplete() == []
    assert p.project(chunk("complete")) == []


def test_incomplete_stream_fails_closed_and_never_fabricates_success():
    p = AGUIEventProjection(thread_id="thread", run_id="run")
    p.begin()
    p.project(chunk("content", "partial"))
    terminal = p.fail_incomplete()
    assert [e["type"] for e in terminal] == ["TEXT_MESSAGE_END", "RUN_ERROR"]
    assert terminal[1]["code"] == "CHAT_SSE_MISSING_TERMINAL"
    assert p.project(chunk("complete")) == []


def test_runtime_errors_have_safe_provenance_and_no_internal_metadata_leak():
    p = AGUIEventProjection(thread_id="thread", run_id="run")
    p.begin()
    error = p.project(chunk(
        "error", "Service unavailable", error_code="PROVIDER_OFFLINE",
        secret="never-expose", model_config={"api_key": "secret"}
    ))
    assert error == [{
        "type": "RUN_ERROR", "message": "Service unavailable",
        "code": "PROVIDER_OFFLINE"
    }]
    assert "never-expose" not in str(error)
    assert "api_key" not in str(error)


def test_agent_activity_does_not_fabricate_langgraph_progress():
    p = AGUIEventProjection(thread_id="thread", run_id="run")
    p.begin()
    events = p.project(chunk(
        "agent_step", "Research", step_id="s1",
        event_type="agent_step_completed", status="completed",
        agent_id="researcher", secret="internal"
    ))
    assert [event["type"] for event in events] == [
        "ACTIVITY_SNAPSHOT", "CUSTOM",
    ]
    assert events[0]["messageId"] == "activity-run-s1"
    assert events[0]["activityType"] == "KAREN_AGENT_STEP"
    assert events[0]["content"]["status"] == "completed"
    assert events[1]["name"] == "karen.agent_step"
    assert events[1]["value"]["status"] == "completed"
    assert "secret" not in str(events)
    assert p.project(chunk("status", "Waiting"))[0]["name"] == "karen.status"


def test_tool_projection_never_exposes_args_or_invents_unseen_start():
    p = AGUIEventProjection(thread_id="thread", run_id="run")
    p.begin()
    assert p.project(chunk(
        "tool", step_id="tool-1", tool_name="search", phase="completed",
        arguments={"token": "secret"}
    )) == []  # A step ID is not a tool-call ID.
    out_of_order = p.project(chunk(
        "tool", tool_call_id="tool-1", tool_name="search", phase="completed",
        arguments={"token": "secret"}
    ))
    assert [event["type"] for event in out_of_order] == ["CUSTOM"]
    started = p.project(chunk(
        "tool", tool_call_id="tool-2", tool_name="search", phase="started",
        arguments={"token": "secret"}
    ))
    finished = p.project(chunk(
        "tool", tool_call_id="tool-2", tool_name="search", phase="completed",
        result={"token": "secret"}
    ))
    assert [event["type"] for event in started] == ["CUSTOM", "TOOL_CALL_START"]
    assert [event["type"] for event in finished] == ["CUSTOM", "TOOL_CALL_END"]
    assert "secret" not in str(started + finished)


def test_citation_and_approval_custom_events_are_allowlisted():
    p = AGUIEventProjection(thread_id="thread", run_id="run")
    p.begin()
    citations = p.project(chunk("citation", citations=[{
        "id": "source-1", "title": "Title",
        "url": "https://example.org", "secret": "private"
    }]))
    assert citations[0]["name"] == "karen.citations"
    assert "private" not in str(citations)
    approval = p.project(chunk(
        "approval", "User approval required", approval_id="a1", token="private"
    ))
    assert approval[0]["value"]["approval_id"] == "a1"
    assert "private" not in str(approval)
    assert not p.terminal


def test_projection_rejects_invalid_state_transitions():
    p = AGUIEventProjection(thread_id="thread", run_id="run")
    with pytest.raises(RuntimeError, match="begin"):
        p.project(chunk("content", "no run"))
    p.begin()
    with pytest.raises(RuntimeError, match="already started"):
        p.begin()
    with pytest.raises(ValueError):
        AGUIEventProjection(thread_id="", run_id="run")


def test_deepagents_step_updates_reuse_one_activity_message():
    p = AGUIEventProjection(thread_id="tenant-scoped-thread", run_id="agent-run")
    p.begin()
    started = p.project(chunk(
        "agent_step", "Agent step running.",
        event_type="agent_step_started", step_id="step-7", agent_id="researcher",
        status="running", execution_engine="deepagents",
    ))
    completed = p.project(chunk(
        "agent_step", "Agent step completed.",
        event_type="agent_step_completed", step_id="step-7", agent_id="researcher",
        status="completed", execution_engine="deepagents",
    ))
    assert started[0]["type"] == "ACTIVITY_SNAPSHOT"
    assert started[0]["messageId"] == completed[0]["messageId"]
    assert started[0]["content"]["status"] == "running"
    assert completed[0]["content"]["status"] == "completed"
    assert not any(e["type"] == "TEXT_MESSAGE_CONTENT" for e in started + completed)


def test_deepagents_tool_failure_does_not_fabricate_result_or_tool_args():
    p = AGUIEventProjection(thread_id="thread", run_id="run")
    p.begin()
    started = p.project(chunk(
        "tool", tool_name="web_search", tool_call_id="real-call-1",
        step_id="step-7", phase="started", arguments={"secret": "hidden"},
    ))
    failed = p.project(chunk(
        "tool", tool_name="web_search", tool_call_id="real-call-1",
        step_id="step-7", phase="failed", result={"secret": "hidden"},
    ))
    assert [e["type"] for e in started] == ["CUSTOM", "TOOL_CALL_START"]
    assert [e["type"] for e in failed] == ["CUSTOM", "TOOL_CALL_END"]
    assert started[1]["toolCallId"] == failed[1]["toolCallId"]
    assert failed[0]["value"]["phase"] == "failed"
    assert "TOOL_CALL_RESULT" not in str(started + failed)
    assert "secret" not in str(started + failed)
    assert p.project(chunk(
        "tool", tool_name="web_search", tool_call_id="real-call-1",
        phase="completed",
    )) == [p._custom("karen.tool_activity", {
        "tool_call_id": "real-call-1", "name": "web_search", "phase": "completed",
    })]


def test_deepagents_events_do_not_cross_run_or_reuse_message_identity():
    def project(run_id):
        p = AGUIEventProjection(thread_id="thread", run_id=run_id)
        p.begin()
        return p.project(chunk(
            "agent_step", status="running",
            step_id="step-1", agent_id="researcher",
        ))[0]["messageId"]
    assert project("run-1") != project("run-2")


def test_missing_agent_identity_never_creates_activity():
    p = AGUIEventProjection(thread_id="thread", run_id="run")
    p.begin()
    assert p.project(chunk("agent_step", status="running", step_id="step-1")) == []
    assert p.project(chunk("agent_step", status="complete",
                           step_id="step-1", agent_id="researcher")) == []


def test_deepagents_opt_in_plan_emits_real_activity_snapshots_only():
    p = AGUIEventProjection(thread_id="tenant-thread", run_id="run-7")
    p.begin()
    start = p.project(chunk(
        "agent_step",
        content="Deep Agents plan running.",
        step_id="deepagents-todo-123",
        agent_id="researcher",
        status="running",
        event_type="deepagents_plan_running",
        source="deepagents",
        activity_kind="plan",
    ))
    complete = p.project(chunk(
        "agent_step",
        content="Deep Agents plan completed.",
        step_id="deepagents-todo-123",
        agent_id="researcher",
        status="completed",
        event_type="deepagents_plan_completed",
        source="deepagents",
        activity_kind="plan",
    ))
    assert start[0]["type"] == "ACTIVITY_SNAPSHOT"
    assert start[0]["activityType"] == "KAREN_DEEPAGENTS_PLAN"
    assert start[0]["messageId"] == complete[0]["messageId"]
    assert start[0]["content"]["status"] == "running"
    assert complete[0]["content"]["status"] == "completed"
    assert not any(e["type"].startswith("SUBAGENT") for e in start + complete)


def test_deepagents_real_task_callback_emits_native_subagent_lifecycle():
    p = AGUIEventProjection(thread_id="tenant-thread", run_id="run-7")
    p.begin()

    def stage(status, callback_id="actual-task-123"):
        return p.project(chunk(
            "agent_step",
            content=f"Deep Agents subagent {status}.",
            step_id=f"deepagents-{callback_id}",
            agent_id="researcher",
            status=status,
            event_type=f"deepagents_subagent_{status}",
            source="deepagents",
            activity_kind="subagent",
            subagent_run_id=callback_id,
            internal_args={"private": "never-reveal"},
        ))

    start = stage("running")
    assert [e["type"] for e in start] == [
        "ACTIVITY_SNAPSHOT", "CUSTOM", "SUBAGENT_STARTED",
    ]
    assert start[0]["activityType"] == "KAREN_DEEPAGENTS_SUBAGENT"
    assert start[2]["subagentRunId"] == "actual-task-123"
    assert start[2]["name"] == "task"
    assert [e["type"] for e in stage("running")] == [
        "ACTIVITY_SNAPSHOT", "CUSTOM",
    ]
    finish = stage("completed")
    assert finish[-1]["type"] == "SUBAGENT_FINISHED"
    assert finish[-1]["subagentRunId"] == start[-1]["subagentRunId"]
    assert "SUBAGENT_FINISHED" not in [e["type"] for e in stage("completed")]
    assert "never-reveal" not in str(start + finish)


def test_deepagents_subagent_failure_is_explicit_but_never_exposes_error():
    p = AGUIEventProjection(thread_id="tenant-thread", run_id="run-8")
    p.begin()
    p.project(chunk(
        "agent_step", "Delegation running",
        step_id="deepagents-task-1", agent_id="researcher",
        status="running", event_type="deepagents_subagent_running",
        source="deepagents", activity_kind="subagent",
        subagent_run_id="actual-task-1",
    ))
    failed = p.project(chunk(
        "agent_step", "Secret provider exception",
        step_id="deepagents-task-1", agent_id="researcher",
        status="failed", event_type="deepagents_subagent_failed",
        source="deepagents", activity_kind="subagent",
        subagent_run_id="actual-task-1", exception="credentials leaked",
    ))
    assert failed[-1] == {
        "type": "SUBAGENT_ERROR", "subagentRunId": "actual-task-1",
        "message": "Delegated task failed.",
    }
    assert "credentials leaked" not in str(failed)
    assert "Secret provider exception" not in str(failed)
    assert failed[0]["content"]["description"] == "Deep Agents subagent failed."


def test_unobserved_subagent_completion_cannot_invent_start_or_finish():
    p = AGUIEventProjection(thread_id="thread", run_id="run")
    p.begin()
    received = p.project(chunk(
        "agent_step", "Task completed",
        step_id="deepagents-not-started",
        agent_id="researcher",
        status="completed", event_type="deepagents_subagent_completed",
        source="deepagents", activity_kind="subagent",
        subagent_run_id="not-started",
    ))
    assert [e["type"] for e in received] == ["ACTIVITY_SNAPSHOT", "CUSTOM"]
