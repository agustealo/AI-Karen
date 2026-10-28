from ai_karen_engine.core.runtime.location_context import resolve_location


def test_runtime_evidence_is_fallback_for_weather():
    result = resolve_location({"location": "Unverified city"}, {"weather_location": "Detroit"}, kind="weather")
    assert result is not None
    assert (result.value, result.source) == ("Detroit", "authorized_runtime")


def test_user_selected_weather_location_precedes_runtime():
    selected = resolve_location(
        {"location_source": "user_selected", "location": "Ann Arbor"},
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


def test_authorized_memory_precedes_consented_device_and_system_location():
    selected = resolve_location(
        {"location_source": "device_with_consent", "location": "Ann Arbor"},
        {"weather_location": "Detroit", "system_location_permitted": True,
         "system_location": "Lansing"},
        kind="weather",
    )
    assert (selected.value, selected.source) == ("Detroit", "authorized_runtime")


def test_system_location_requires_explicit_permission():
    context = {"system_location": "Lansing"}
    assert resolve_location({}, context, kind="weather") is None
    selected = resolve_location(
        {}, {**context, "system_location_permitted": True}, kind="weather"
    )
    assert (selected.value, selected.source) == ("Lansing", "system_with_permission")


def test_user_selected_place_precedes_every_other_tier():
    selected = resolve_location(
        {"location_source": "user_selected", "location": "Chicago"},
        {"weather_location": "Detroit", "system_location_permitted": True,
         "system_location": "Lansing"}, kind="weather"
    )
    assert (selected.value, selected.source) == ("Chicago", "user_selected")


def test_clock_uses_authorized_timezone_before_system_timezone():
    selected = resolve_location(
        {}, {"timezone": "America/Detroit", "system_timezone_permitted": True,
             "system_timezone": "America/Chicago"}, kind="time"
    )
    assert (selected.value, selected.source) == ("America/Detroit", "authorized_runtime")


def test_clock_only_uses_system_timezone_if_permitted():
    assert resolve_location({}, {"system_timezone": "America/Detroit"}, kind="time") is None
    selected = resolve_location(
        {}, {"system_timezone": "America/Detroit",
             "system_timezone_permitted": True}, kind="time"
    )
    assert (selected.value, selected.source) == ("America/Detroit", "system_with_permission")


def test_spoofed_profile_provenance_does_not_override_authorized_memory():
    result = resolve_location(
        {"location_source": "user_profile", "weather_location": "Untrusted"},
        {"weather_location": "Detroit"}, kind="weather",
    )
    assert (result.value, result.source) == ("Detroit", "authorized_runtime")


def test_device_location_needs_server_permission():
    metadata = {"location_source": "device_with_consent", "location": "Ann Arbor"}
    assert resolve_location(metadata, {}, kind="weather") is None
    result = resolve_location(
        metadata, {"device_location_permitted": True}, kind="weather",
    )
    assert (result.value, result.source) == ("Ann Arbor", "device_with_consent")


def test_device_timezone_needs_server_permission():
    metadata = {"timezone_source": "device_with_consent", "timezone": "America/Detroit"}
    assert resolve_location(metadata, {}, kind="time") is None
    result = resolve_location(
        metadata, {"device_timezone_permitted": True}, kind="time",
    )
    assert (result.value, result.source) == ("America/Detroit", "device_with_consent")
