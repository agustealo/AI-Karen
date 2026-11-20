"""CK-GEN-01A: charts use only observed, authorized Fahrenheit source values."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime


def _execution(
    *,
    prompt="Chart the reported Detroit high and low temperatures",
    high=70.5,
    low=50,
    success=True,
    degraded=False,
    source="tool",
    allowed_tools=("weather_tool",),
    allowed_plugins=(),
    attempts=None,
    payload=None,
    intent="search.weather",
):
    request = SimpleNamespace(
        context=SimpleNamespace(request_id="request-verified-1", correlation_id="trace-1"),
        messages=[{"role": "user", "content": prompt}],
    )
    decision = SimpleNamespace(intent=intent)
    plan = SimpleNamespace(
        allowed_tools=allowed_tools,
        allowed_plugins=allowed_plugins,
    )
    result = SimpleNamespace(
        success=success,
        degraded=degraded,
        source=source,
        source_id="weather_tool",
        attempts=(
            [{"type": source, "id": "weather_tool", "status": "success"}]
            if attempts is None else attempts
        ),
        payload=(
            {"weather": {
                "location": "Detroit",
                "temperature_f": 60.3,
                "high_f": high,
                "low_f": low,
                "debug_token": "not-for-ui",
            }}
            if payload is None else payload
        ),
    )
    return request, decision, plan, result


def test_chart_is_exactly_source_measured_and_reuses_weather_evidence_identity():
    request, decision, plan, result = _execution()
    original = ChatRuntime._verified_weather_presentation(request, decision, plan, result)
    chart = ChatRuntime._verified_weather_chart_presentation(request, decision, plan, result)

    assert original is not None
    assert chart is not None
    assert chart["component_type"] == "chart.bar"
    assert chart["evidence_ref"] == original["evidence_ref"] == "request-verified-1:weather_tool"
    assert chart["correlation_id"] == "trace-1"
    assert chart["data"]["unit"] == "°F"
    assert chart["data"]["points"] == [
        {"label": "High", "value": 70.5},
        {"label": "Low", "value": 50},
    ]
    assert "debug_token" not in repr(chart)
    assert ChatRuntime._collect_authorized_surface_parts(
        request, [(decision, plan, result)]
    ) == [chart]


def test_ordinary_weather_request_keeps_existing_observation_card():
    request, decision, plan, result = _execution(prompt="What's the weather in Detroit?")
    assert ChatRuntime._verified_weather_chart_presentation(
        request, decision, plan, result
    ) is None
    parts = ChatRuntime._collect_authorized_surface_parts(
        request, [(decision, plan, result)]
    )
    assert len(parts) == 1
    assert parts[0]["component_type"] == "weather.observation"


@pytest.mark.parametrize("overrides", [
    {"success": False},
    {"degraded": True},
    {"source": "model"},
    {"source": "plugin"},
    {"allowed_tools": ()},
    {"attempts": []},
    {"attempts": [{"type": "tool", "id": "weather_tool", "status": "failed"}]},
    {"attempts": [{"type": "plugin", "id": "weather_tool", "status": "success"}]},
    {"intent": "search.general"},
])
def test_unauthorized_failed_or_wrong_intent_never_admits_chart(overrides):
    request, decision, plan, result = _execution(**overrides)
    assert ChatRuntime._verified_weather_chart_presentation(
        request, decision, plan, result
    ) is None


@pytest.mark.parametrize("high,low", [
    (70.5, -4),
    (151, 60),
    (30, 40),
    ("70", 50),
    (70, "50"),
    (True, 50),
    (70, False),
    (float("nan"), 50),
    (70, float("inf")),
    (float("-inf"), 10),
    (10**200, 2),
    (None, 50),
])
def test_uncomparable_or_nonfinite_measurements_fail_closed(high, low):
    request, decision, plan, result = _execution(high=high, low=low)
    assert ChatRuntime._verified_weather_chart_presentation(
        request, decision, plan, result
    ) is None


def test_absent_source_measurements_or_model_authored_presentation_cannot_create_chart():
    request, decision, plan, result = _execution(
        payload={"weather": {"location": "Detroit", "temperature_f": 60.3},
                 "presentation": {"component_type": "chart.bar", "data": {
                     "points": [{"label": "fabricated", "value": 999999}]
                 }}}
    )
    assert ChatRuntime._verified_weather_chart_presentation(
        request, decision, plan, result
    ) is None


def test_valid_weather_plugin_uses_same_authentication_gate():
    request, decision, plan, result = _execution(
        source="plugin", allowed_tools=(), allowed_plugins=("weather_tool",),
    )
    chart = ChatRuntime._verified_weather_chart_presentation(
        request, decision, plan, result
    )
    assert chart is not None
    assert chart["data"]["points"][0]["value"] == 70.5
    plan.allowed_plugins = ()
    assert ChatRuntime._verified_weather_chart_presentation(
        request, decision, plan, result
    ) is None
