"""Runtime presentation contract remains independent of AG-UI transport."""

from ai_karen_engine.core.runtime.presentation_contract import validate_presentation


def test_presentations_are_minimized_identically_for_runtime_and_projection():
    evidence = {
        "schema_version": 1,
        "presentation_id": "weather-1",
        "component_type": "weather.observation",
        "evidence_ref": "request-1:tool-weather",
        "data": {
            "location": "Detroit",
            "temperature_f": 60.3,
            "wind_speed_mph": 0.3,
            "secret_token": "must-not-serialize",
            "debug_trace": {"private": "internal"},
        },
    }
    actual = validate_presentation(evidence)
    assert actual is not None
    assert actual["data"] == {
        "location": "Detroit",
        "temperature_f": 60.3,
        "wind_speed_mph": 0.3,
    }
    assert "must-not-serialize" not in str(actual)


def test_runtime_rejects_incomplete_or_unsafe_envelopes():
    base = {
        "schema_version": 1,
        "presentation_id": "weather-1",
        "component_type": "weather.observation",
        "evidence_ref": "request-1:weather",
        "data": {"location": "Detroit", "temperature_f": 60.3},
    }
    for broken in (
        {**base, "evidence_ref": ""},
        {**base, "component_type": "unsafe.code"},
        {**base, "data": {"location": "Detroit", "temperature_f": "60%"}},
        {**base, "data": {"location": "Detroit", "temperature_f": float("nan")}},
        {**base, "data": {"location": "Detroit", "temperature_f": 60.3, "private": "x" * 40000}},
    ):
        if broken["data"].get("private"):
            assert validate_presentation(broken)["data"] == {"location": "Detroit", "temperature_f": 60.3}
        else:
            assert validate_presentation(broken) is None


def test_planner_task_list_is_read_only_and_strips_unapproved_fields():
    envelope = {
        "schema_version": 1,
        "presentation_id": "tasks-1",
        "component_type": "planner.task_list",
        "evidence_ref": "authorized-planner-read-1",
        "data": {"tasks": [{
            "id": "task-1", "title": "Review draft", "status": "todo",
            "action_url": "https://untrusted.invalid/delete",
            "secret": "never expose",
        }]},
    }
    result = validate_presentation(envelope)
    assert result is not None
    assert result["data"] == {"tasks": [{
        "id": "task-1", "title": "Review draft", "status": "todo",
    }]}
    assert validate_presentation({
        **envelope, "data": {"tasks": [{"id": "task-1", "title": "Review", "status": "executed"}]},
    }) is None
    assert validate_presentation({
        **envelope, "data": {"tasks": []},
    }) is None


def test_weather_fahrenheit_strings_parse_without_being_relabelled():
    base = {
        "schema_version": 1,
        "presentation_id": "weather-observation-1",
        "component_type": "weather.observation",
        "evidence_ref": "authorized-weather-read",
        "data": {"location": "Detroit", "temperature": "60.3°F"},
    }
    assert validate_presentation(base) is not None
    assert validate_presentation({
        **base, "data": {"location": "Detroit", "temperature_f": "60.3"},
    }) is not None
    assert validate_presentation({
        **base, "data": {"location": "Detroit", "temperature": "60.3"},
    }) is None
