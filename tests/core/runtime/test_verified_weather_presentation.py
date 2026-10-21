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
