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
    assert events[0]["type"] == "CUSTOM"
    assert events[0]["name"] == "karen.agent_step"
    assert events[0]["value"]["status"] == "completed"
    assert "secret" not in str(events)
    assert p.project(chunk("status", "Waiting"))[0]["name"] == "karen.status"


def test_tool_projection_never_exposes_args_or_invents_unseen_start():
    p = AGUIEventProjection(thread_id="thread", run_id="run")
    p.begin()
    out_of_order = p.project(chunk(
        "tool", step_id="tool-1", tool_name="search", phase="completed",
        arguments={"token": "secret"}
    ))
    assert [event["type"] for event in out_of_order] == ["CUSTOM"]
    started = p.project(chunk(
        "tool", step_id="tool-2", tool_name="search", phase="started",
        arguments={"token": "secret"}
    ))
    finished = p.project(chunk(
        "tool", step_id="tool-2", tool_name="search", phase="completed",
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
