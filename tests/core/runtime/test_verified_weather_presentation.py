"""Presentation generation requires authorized, successful runtime evidence."""

from types import SimpleNamespace

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
