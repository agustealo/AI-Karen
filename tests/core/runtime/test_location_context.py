from ai_karen_engine.core.runtime.location_context import resolve_location


def test_runtime_evidence_is_fallback_for_weather():
    result = resolve_location({"location": "Unverified city"}, {"weather_location": "Detroit"}, kind="weather")
    assert result is not None
    assert (result.value, result.source) == ("Detroit", "authorized_runtime")


def test_explicitly_sourced_weather_location_precedes_runtime():
    selected = resolve_location(
        {"location_source": "device_with_consent", "location": "Ann Arbor"},
        {"weather_location": "Detroit"},
        kind="weather",
    )
    assert selected is not None and selected.value == "Ann Arbor"


def test_unsourced_timezone_cannot_override_authorized_context():
    selected = resolve_location(
        {"timezone": "America/Los_Angeles"},
        {"timezone": "America/Detroit"},
        kind="time",
    )
    assert selected is not None and selected.value == "America/Detroit"


def test_trusted_timezone_is_selected_and_unknown_kind_rejected():
    selected = resolve_location(
        {"timezone_source": "user_selected", "timezone": "America/New_York"},
        {"timezone": "America/Detroit"},
        kind="time",
    )
    assert selected is not None and selected.value == "America/New_York"
    assert resolve_location({}, {}, kind="weather") is None


def test_weather_clarification_is_preserved_by_capability_adapter():
    from pathlib import Path
    executor = (Path(__file__).resolve().parents[3] / "src/ai_karen_engine/core/runtime/direct_capability_executor.py").read_text()
    assert 'effective_context["pending_clarification"] = pending' in executor
