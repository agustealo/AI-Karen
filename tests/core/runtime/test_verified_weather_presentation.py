"""Presentation generation requires authorized, successful runtime evidence."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime


def _run(*, success=True, degraded=False, source="tool", allowed=("weather_tool",), attempts=None):
    request = SimpleNamespace(context=SimpleNamespace(request_id="req-1", correlation_id="corr-1"))
    decision = SimpleNamespace(intent="search.weather")
    plan = SimpleNamespace(allowed_tools=allowed)
    result = SimpleNamespace(
        success=success,
        degraded=degraded,
        source=source,
        source_id="weather_tool",
        attempts=[{"type": "tool", "id": "weather_tool", "status": "success"}] if attempts is None else attempts,
        payload={"extractedData": {"location": "Detroit", "temperature_f": 60.3}},
    )
    return ChatRuntime._verified_weather_presentation(request, decision, plan, result)


def test_authorized_successful_weather_result_builds_valid_presentation():
    presentation = _run()
    assert presentation is not None
    assert presentation["component_type"] == "weather.observation"
    assert presentation["data"]["temperature_f"] == 60.3
    assert presentation["evidence_ref"] == "req-1:weather_tool"


def test_denied_failed_or_degraded_tool_never_generates_presentation():
    assert _run(success=False) is None
    assert _run(degraded=True) is None
    assert _run(source="plugin") is None
    assert _run(allowed=()) is None
    assert _run(attempts=[{"type": "tool", "id": "weather_tool", "status": "failed"}]) is None


def test_planner_presentations_require_authorized_service_result():
    decision = SimpleNamespace(intent="planner.read")
    plan = SimpleNamespace(allowed_capabilities=("planner.read",))
    envelope = {
        "schema_version": 1, "presentation_id": "planner-1",
        "component_type": "planner.task_list",
        "evidence_ref": "planner-owned-read:1",
        "data": {"tasks": [{"id": "1", "title": "Review project", "status": "todo"}]},
    }
    result = SimpleNamespace(
        success=True, degraded=False, source="planner",
        source_id="planner.read", payload={"presentation": envelope},
    )
    assert ChatRuntime._verified_planner_presentation(decision, plan, result) == envelope
    assert ChatRuntime._verified_planner_presentation(
        decision, SimpleNamespace(allowed_capabilities=()), result,
    ) is None
    result.source = "model"
    assert ChatRuntime._verified_planner_presentation(decision, plan, result) is None


def test_time_plugin_presentation_requires_authorized_success_receipt():
    from types import SimpleNamespace

    request = SimpleNamespace(context=SimpleNamespace(request_id="req-1", correlation_id="corr-1"))
    decision = SimpleNamespace(intent="time.current")
    plugin = "time-query"
    plan = SimpleNamespace(allowed_tools=(), allowed_plugins=(plugin,))
    result = SimpleNamespace(
        success=True, degraded=False, source="plugin", source_id=plugin,
        attempts=[{"type": "plugin", "id": plugin, "status": "success"}],
        payload={"formatted": "10:15 AM", "timezone": "America/Detroit"},
    )
    projected = ChatRuntime._verified_weather_presentation(request, decision, plan, result)
    assert projected is not None
    assert projected["component_type"] == "time.observation"
    assert projected["evidence_ref"] == "req-1:time-query"
    assert ChatRuntime._verified_weather_presentation(
        request, decision, SimpleNamespace(allowed_tools=(), allowed_plugins=()), result
    ) is None
    result.attempts = [{"type": "plugin", "id": plugin, "status": "failed"}]
    assert ChatRuntime._verified_weather_presentation(request, decision, plan, result) is None
    result.attempts = [{"type": "plugin", "id": plugin, "status": "success"}]
    result.source = "model"
    assert ChatRuntime._verified_weather_presentation(request, decision, plan, result) is None

@pytest.mark.asyncio
async def test_first_streamed_presentation_matches_final_runtime_captured_envelope(monkeypatch):
    """A finalized surface is never stale after the authorized composition stage."""
    from unittest.mock import AsyncMock
    from ai_karen_engine.core.runtime import chat_runtime

    original = {
        "schema_version": 1,
        "presentation_id": "clock-observed",
        "component_type": "time.observation",
        "evidence_ref": "req-1:time-query",
        "data": {"formatted": "10:42 PM", "timezone": "America/Detroit"},
    }
    final = {**original, "display": {"density": "compact"}}
    result = SimpleNamespace(
        success=True, degraded=False, normalized_metadata=lambda: {},
    )
    executor = SimpleNamespace(execute=AsyncMock(return_value=result))
    monkeypatch.setattr(chat_runtime, "get_direct_capability_executor", lambda: executor)
    monkeypatch.setattr(
        chat_runtime.RuntimeEvidenceResolver,
        "authorized_semantic_value",
        lambda *args, **kwargs: None,
    )

    class RuntimeStub:
        def _pending_clarification_from_result(self, request, result):
            return None

        def _collect_authorized_surface_parts(self, request, executions):
            return [original]

        async def _compose_direct_capability_answer(
            self, request, decision, plan, meter, result, normalized,
        ):
            return "Observed current time", {
                **normalized, "structured_content": {"presentation": final},
                "response_source": "grounded_observation_model",
            }

    context = SimpleNamespace(
        request_id="req-1", correlation_id="corr-1",
        user_id="user-1", tenant_id="tenant-1",
    )
    request = SimpleNamespace(context=context)
    decision = SimpleNamespace(intent="time.current", cognitive_context=None)
    metadata = {}
    chunks = [
        chunk async for chunk in ChatRuntime._run_direct_capability_stream(
            RuntimeStub(), request, decision, SimpleNamespace(),
            SimpleNamespace(), _meta=metadata,
        )
    ]
    assert [str(getattr(chunk.type, "value", chunk.type)) for chunk in chunks] == [
        "content", "presentation",
    ]
    assert chunks[1].metadata["presentation_verified"] is True
    assert chunks[1].metadata["presentation"] == final
    assert metadata["structured_content"]["presentation"] == final
    assert chunks[1].metadata["presentation"] != original


@pytest.mark.asyncio
async def test_stream_rejects_invalid_final_presentation_even_with_original_capability_evidence(monkeypatch):
    from unittest.mock import AsyncMock
    from ai_karen_engine.core.runtime import chat_runtime

    original = {
        "schema_version": 1, "presentation_id": "clock-observed",
        "component_type": "time.observation", "evidence_ref": "req-1:clock",
        "data": {"formatted": "10:42 PM"},
    }
    fake_result = SimpleNamespace(normalized_metadata=lambda: {})
    monkeypatch.setattr(chat_runtime, "get_direct_capability_executor",
                        lambda: SimpleNamespace(execute=AsyncMock(return_value=fake_result)))
    monkeypatch.setattr(chat_runtime.RuntimeEvidenceResolver,
                        "authorized_semantic_value", lambda *args, **kw: None)

    class RuntimeStub:
        def _pending_clarification_from_result(self, request, result):
            return None

        def _collect_authorized_surface_parts(self, request, executions):
            return [original]

        async def _compose_direct_capability_answer(self, *args):
            return "Verified observation", {
                "structured_content": {"presentation": {
                    **original, "data": {"formatted": "10:42 PM", "private": "unverified"},
                    "component_type": "untrusted.code",
                }},
            }

    request = SimpleNamespace(context=SimpleNamespace(
        request_id="req-1", correlation_id="corr-1",
        user_id="user-1", tenant_id="tenant-1",
    ))
    decision = SimpleNamespace(intent="time.current", cognitive_context=None)
    chunks = [
        c async for c in ChatRuntime._run_direct_capability_stream(
            RuntimeStub(), request, decision, SimpleNamespace(), SimpleNamespace(),
        )
    ]
    assert len(chunks) == 1
    assert str(getattr(chunks[0].type, "value", chunks[0].type)) == "content"
