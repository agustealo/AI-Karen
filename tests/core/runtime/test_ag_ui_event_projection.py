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
    assert events[0]["content"]["runId"] == "run"
    assert "eventId" not in events[0]["content"]  # No fabricated persisted-event identity.
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


def test_checkpoint_status_requires_acknowledged_persistence_and_never_implies_resume():
    p = AGUIEventProjection(thread_id="tenant-thread", run_id="run-1")
    p.begin()
    events = p.project(chunk(
        "status",
        "Agent state checkpoint persisted. Automatic resume is not enabled.",
        source="deepagents", step_id="step-1",
        checkpoint_verified=True, resumable=False,
        checkpoint_bytes={"password": "must-not-leak"},
    ))
    assert events == [{
        "type": "CUSTOM", "name": "karen.checkpoint",
        "value": {
            "step_id": "step-1",
            "checkpoint_verified": True,
            "resumable": False,
            "message": "Agent checkpoint persisted. Resume is not available.",
        },
    }]
    assert "must-not-leak" not in str(events)


def test_checkpoint_without_verifiable_saved_state_is_only_an_ordinary_status():
    p = AGUIEventProjection(thread_id="thread", run_id="run")
    p.begin()
    events = p.project(chunk(
        "status", "Checkpoint requested",
        source="deepagents", step_id="step-1",
        checkpoint_verified=False, resumable=True,
    ))
    assert not any(e.get("name") == "karen.checkpoint" for e in events)
    assert not any(e.get("value", {}).get("resumable") is True for e in events)


def test_deepagents_content_discloses_learning_provenance_without_private_memory():
    p = AGUIEventProjection(thread_id="tenant-thread", run_id="run-1")
    p.begin()
    events = p.project(chunk(
        "content", "Finished research.",
        execution_engine="deepagents",
        model_selection_source="learning_operational_reliability_v1",
        learning_signal_status="ready",
        learning_signal_version="model_operational_outcome_v1",
        learned_context_status="resolved",
        learned_memory_refs_included=2,
        raw_memory={"secret": "must-not-appear"},
        learned_model_scores={"unverified_quality": 100},
    ))
    assert [e["type"] for e in events] == [
        "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "CUSTOM",
    ]
    assert events[2]["name"] == "karen.learning_decision"
    assert events[2]["value"] == {
        "selection_source": "learning_operational_reliability_v1",
        "learning_signal_status": "ready",
        "learning_signal_version": "model_operational_outcome_v1",
        "learned_context_status": "resolved",
        "included_memory_refs": 2,
        "claim": "operational_evidence_only",
    }
    assert "must-not-appear" not in str(events)
    assert "unverified_quality" not in str(events)


def test_agui_does_not_fabricate_learning_on_unobserved_activity():
    p = AGUIEventProjection(thread_id="thread", run_id="run")
    p.begin()
    events = p.project(chunk(
        "content", "Answer",
        execution_engine="deepagents",
        model_selection_source="the_model_is_genius",
        learning_signal_status="ready",
        learned_memory_refs_included=-15,
    ))
    assert [e["type"] for e in events] == [
        "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT",
    ]


def test_agui_cannot_repeat_learning_badge_on_incremental_chunks():
    p = AGUIEventProjection(thread_id="thread", run_id="run")
    p.begin()
    args = {
        "execution_engine": "deepagents",
        "model_selection_source": "baseline_insufficient_evidence",
        "learning_signal_status": "cold_start",
    }
    first = p.project(chunk("content", "Part A", **args))
    second = p.project(chunk("content", "Part B", **args))
    assert len([event for event in first + second
                if event.get("name") == "karen.learning_decision"]) == 1


def test_agui_reports_shadow_learning_without_claiming_an_active_model_switch():
    p = AGUIEventProjection(thread_id="tenant-thread", run_id="run-shadow")
    p.begin()
    events = p.project(chunk(
        "content", "Research result",
        execution_engine="deepagents",
        model_selection_source="shadow_operational_recommendation",
        learning_signal_status="ready",
        learning_signal_version="model_operational_outcome_v1",
        learned_context_status="resolved",
        learned_memory_refs_included=2,
        recommended_model="unpromoted-model-b",
        raw_memory={"secret": "private"},
    ))
    provenance = next(
        e for e in events if e.get("name") == "karen.learning_decision"
    )["value"]
    assert provenance["selection_source"] == "shadow_operational_recommendation"
    assert provenance["claim"] == "operational_evidence_only"
    assert "unpromoted-model-b" not in str(events)
    assert "private" not in str(events)


def test_presentation_requires_verified_bounded_runtime_evidence():
    envelope = {
        "schema_version": 1,
        "presentation_id": "p-1",
        "component_type": "weather.observation",
        "data": {"location": "Detroit", "temperature_f": 60.3},
        "evidence_ref": "tool-receipt-1",
    }
    projection = AGUIEventProjection(thread_id="thread", run_id="run")
    projection.begin()
    assert projection.project(chunk("presentation", presentation=envelope)) == []
    assert projection.project(chunk(
        "presentation", presentation=envelope, presentation_verified=False
    )) == []
    events = projection.project(chunk(
        "presentation", presentation=envelope, presentation_verified=True
    ))
    assert events == [{
        "type": "CUSTOM", "name": "karen.presentation.v1", "value": envelope,
    }]
    invalid = [
        {**envelope, "component_type": "javascript"},
        {**envelope, "evidence_ref": ""},
        {**envelope, "data": {"text": "x" * 40000}},
        {**envelope, "schema_version": True},
        {**envelope, "data": {"value": float("nan")}},
        {**envelope, "unexpected": "ignored"},
    ]
    for bad in invalid:
        assert projection.project(chunk(
            "presentation", presentation=bad, presentation_verified=True
        )) == []


def test_presentation_rejects_verified_flag_when_weather_evidence_is_invalid():
    base = {
        "schema_version": 1,
        "presentation_id": "weather-1",
        "component_type": "weather.observation",
        "evidence_ref": "receipt-1",
    }
    p = AGUIEventProjection(thread_id="thread", run_id="run")
    p.begin()
    for bad in (
        {"location": "Detroit"},
        {"location": "Detroit", "temperature_f": "60%"},
        {"location": "Detroit", "temperature_f": 60, "temperatureF": 85},
        {"location": "Detroit", "temperature_f": float("inf")},
        {"location": "", "temperature_f": 60},
    ):
        assert p.project(chunk("presentation", presentation={
            **base, "data": bad,
        }, presentation_verified=True)) == []
    valid = {**base, "data": {"location": "Detroit", "temperature_f": 60.3}}
    assert p.project(chunk(
        "presentation", presentation=valid, presentation_verified=True
    ))[0]["name"] == "karen.presentation.v1"
