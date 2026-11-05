"""Presentation generation requires authorized, successful runtime evidence."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime


def _run(*, success=True, degraded=False, source="tool", allowed=("weather_tool",), allowed_plugins=(), attempts=None, payload=None):
    request = SimpleNamespace(context=SimpleNamespace(request_id="req-1", correlation_id="corr-1"))
    decision = SimpleNamespace(intent="search.weather")
    plan = SimpleNamespace(allowed_tools=allowed, allowed_plugins=allowed_plugins)
    result = SimpleNamespace(
        success=success,
        degraded=degraded,
        source=source,
        source_id="weather_tool",
        attempts=[{"type": "tool", "id": "weather_tool", "status": "success"}] if attempts is None else attempts,
        payload=payload if payload is not None else {
            "extractedData": {"location": "Detroit", "temperature_f": 60.3},
        },
    )
    return ChatRuntime._verified_weather_presentation(request, decision, plan, result)


def test_authorized_successful_weather_result_builds_valid_presentation():
    presentation = _run()
    assert presentation is not None
    assert presentation["component_type"] == "weather.observation"
    assert presentation["data"]["temperature_f"] == 60.3
    assert presentation["evidence_ref"] == "req-1:weather_tool"


@pytest.mark.parametrize("key", ["extractedData", "weather", "current", "observation"])
def test_all_canonical_weather_evidence_shapes_render_first_prompt(key):
    # This is the same response shape returned by the live web_search tool.
    # A valid tool reading must produce the surface on the very first request.
    reading = {
        "location": "Detroit", "temperature": "61°F",
        "conditions": "light rain", "precipitation": "40%",
        "private_debug_token": "must-never-render",
    }
    projected = _run(payload={key: reading})
    assert projected is not None
    assert projected["component_type"] == "weather.observation"
    assert projected["data"]["location"] == "Detroit"
    assert projected["data"]["temperature"] == "61°F"
    assert projected["data"]["conditions"] == "light rain"
    assert "private_debug_token" not in str(projected)
    assert projected["evidence_ref"] == "req-1:weather_tool"
    assert projected["correlation_id"] == "corr-1"


def test_valid_observation_after_invalid_extracted_data_can_still_render():
    projected = _run(payload={
        "extractedData": {"location": "incomplete", "temperature": "not verified"},
        "weather": {"location": "Detroit", "temperature": "61°F"},
    })
    assert projected is not None
    assert projected["data"] == {"location": "Detroit", "temperature": "61°F"}


@pytest.mark.parametrize("payload", [
    {"weather": {"location": "Detroit", "temperature": "61"}},
    {"weather": {"location": "Detroit", "temperature_f": 800}},
    {"weather": {"location": "Detroit", "conditions": "fine"}},
    {"weather": {"temperature": "61°F"}},
    {"results": [{"url": "https://example.com", "snippet": "Weather in Detroit"}]},
])
def test_search_snippets_or_unverified_measurements_cannot_create_weather_cards(payload):
    assert _run(payload=payload) is None


def test_weather_source_must_have_an_authorized_successful_tool_receipt_even_if_data_valid():
    measured = {"weather": {"location": "Detroit", "temperature": "61°F"}}
    assert _run(payload=measured, success=False) is None
    assert _run(payload=measured, degraded=True) is None
    assert _run(payload=measured, source="model") is None
    assert _run(payload=measured, source="plugin") is None
    assert _run(payload=measured, allowed=()) is None
    assert _run(payload=measured, attempts=[
        {"type": "tool", "id": "weather_tool", "status": "failed"},
    ]) is None


def test_authorized_weather_plugin_fallback_emits_same_attested_ui():
    measured = {"observation": {"location": "Detroit", "temperature": "61°F"}}
    projected = _run(
        payload=measured, source="plugin",
        allowed_plugins=("weather_tool",),
        attempts=[{"type": "plugin", "id": "weather_tool", "status": "success"}],
    )
    assert projected is not None
    assert projected["component_type"] == "weather.observation"
    assert projected["data"]["temperature"] == "61°F"
    assert projected["evidence_ref"] == "req-1:weather_tool"

    assert _run(
        payload=measured, source="plugin", allowed_plugins=(),
        attempts=[{"type": "plugin", "id": "weather_tool", "status": "success"}],
    ) is None
    assert _run(
        payload=measured, source="plugin", allowed_plugins=("weather_tool",),
        attempts=[{"type": "plugin", "id": "weather_tool", "status": "failed"}],
    ) is None
    assert _run(
        payload=measured, source="plugin", allowed_plugins=("weather_tool",),
        attempts=[{"type": "tool", "id": "weather_tool", "status": "success"}],
    ) is None


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
