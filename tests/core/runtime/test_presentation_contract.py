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


def test_verified_time_presentation_is_bounded_and_minimized():
    base = {
        "schema_version": 1,
        "presentation_id": "time-request-1",
        "component_type": "time.observation",
        "evidence_ref": "request-1:clock",
        "data": {
            "formatted": "10:15 AM",
            "timezone": "America/Detroit",
            "secret_token": "do-not-project",
        },
    }
    clean = validate_presentation(base)
    assert clean is not None
    assert clean["data"] == {"formatted": "10:15 AM", "timezone": "America/Detroit"}
    assert validate_presentation({**base, "data": {"timezone": "America/Detroit"}}) is None
    assert validate_presentation({**base, "data": {"formatted": "X" * 161}}) is None
    assert validate_presentation({**base, "data": {"formatted": {"unsafe": True}}}) is None


def test_composed_surface_reuses_validated_evidence_bound_children():
    child = {
        "schema_version": 1,
        "presentation_id": "clock-1",
        "component_type": "time.observation",
        "evidence_ref": "request-1:clock",
        "data": {"formatted": "10:15 AM", "secret": "discard"},
    }
    composite = {
        "schema_version": 1,
        "presentation_id": "surface-1",
        "component_type": "surface.composition",
        "evidence_ref": "request-1:clock",
        "data": {"layout": "grid", "items": [child]},
    }
    safe = validate_presentation(composite)
    assert safe is not None
    assert safe["data"]["items"][0]["data"] == {"formatted": "10:15 AM"}
    assert validate_presentation({
        **composite, "data": {"layout": "grid", "items": [
            {**child, "evidence_ref": "different-tenant:clock"}]},
    }) is None
    assert validate_presentation({
        **composite, "data": {"layout": "grid", "items": [composite]},
    }) is None
    assert validate_presentation({
        **composite, "data": {"layout": "grid", "items": [child] * 7},
    }) is None
    assert validate_presentation({
        **composite, "data": {"layout": "iframe", "items": [child]},
    }) is None


def test_layout_proposal_may_only_reorder_authorized_parts():
    from ai_karen_engine.core.runtime.presentation_contract import compose_authorized_surface

    verified = {
        "schema_version": 1, "presentation_id": "clock-1",
        "component_type": "time.observation", "evidence_ref": "tenant-request:clock",
        "data": {"formatted": "10:15 AM", "timezone": "America/Detroit"},
    }
    kwargs = dict(
        presentation_id="surface-1",
        evidence_ref="tenant-request:clock",
        authorized_parts=[verified],
    )
    safe = compose_authorized_surface(
        **kwargs, proposed_layout={"layout": "grid", "part_ids": ["clock-1"]}
    )
    assert safe is not None
    assert safe["data"]["items"][0]["data"]["formatted"] == "10:15 AM"
    assert compose_authorized_surface(
        **kwargs, proposed_layout={"layout": "grid", "part_ids": ["clock-other"]}
    ) is None
    assert compose_authorized_surface(
        **kwargs, proposed_layout={"layout": "grid", "part_ids": ["clock-1", "clock-1"]}
    ) is None
    assert compose_authorized_surface(
        **kwargs, proposed_layout={"layout": "grid", "part_ids": ["clock-1"], "data": {"formatted": "faked"}}
    ) is None
    assert compose_authorized_surface(
        **{**kwargs, "evidence_ref": "another-tenant:clock"},
        proposed_layout={"layout": "grid", "part_ids": ["clock-1"]},
    ) is None


def test_multi_evidence_surface_requires_explicit_authorized_manifest():
    from ai_karen_engine.core.runtime.presentation_contract import compose_authorized_surface

    def clock(name, evidence):
        return {
            "schema_version": 1, "presentation_id": name,
            "component_type": "time.observation", "evidence_ref": evidence,
            "data": {"formatted": "10:15 AM"},
        }

    parts = [clock("a", "receipt-a"), clock("b", "receipt-b")]
    kwargs = {
        "presentation_id": "surface", "evidence_ref": "request-bundle",
        "authorized_parts": parts,
        "proposed_layout": {"layout": "grid", "part_ids": ["b", "a"]},
    }
    assert compose_authorized_surface(**kwargs) is None
    rendered = compose_authorized_surface(
        **kwargs, authorized_evidence_refs=["receipt-a", "receipt-b"]
    )
    assert rendered is not None
    assert rendered["data"]["evidence_refs"] == ["receipt-b", "receipt-a"]
    assert [part["presentation_id"] for part in rendered["data"]["items"]] == ["b", "a"]
    assert compose_authorized_surface(
        **kwargs, authorized_evidence_refs=["receipt-a"]
    ) is None
    assert validate_presentation({
        **rendered, "data": {
            **rendered["data"], "evidence_refs": ["receipt-a", "injected"],
        },
    }) is None
    assert validate_presentation({
        **rendered, "data": {
            **rendered["data"], "evidence_refs": ["receipt-a", "receipt-a"],
        },
    }) is None


def test_source_selected_display_density_is_governed():
    base = {
        "schema_version": 1,
        "presentation_id": "clock-1",
        "component_type": "time.observation",
        "evidence_ref": "observed-clock",
        "data": {"formatted": "16:57:05", "timezone": "UTC"},
    }
    approved = validate_presentation({**base, "display": {"density": "compact"}})
    assert approved is not None
    assert approved["display"] == {"density": "compact"}
    for invalid in (
        {"density": "full-screen"},
        {"density": "compact", "javascript": "alert(1)"},
        {"density": 42},
    ):
        assert validate_presentation({**base, "display": invalid}) is None


def test_date_observation_is_calendar_valid_and_evidence_bound():
    base = {
        "schema_version": 1,
        "presentation_id": "date-1",
        "component_type": "date.observation",
        "evidence_ref": "request-1:time-query",
        "data": {
            "formatted": "2026-10-29",
            "timezone": "America/Detroit",
            "secret": "never-project",
        },
    }
    clean = validate_presentation(base)
    assert clean is not None
    assert clean["data"] == {
        "formatted": "2026-10-29",
        "timezone": "America/Detroit",
    }
    for invalid in ("2026-02-30", "2026-10-24T12:00Z", "date unknown"):
        assert validate_presentation({
            **base, "data": {"formatted": invalid}
        }) is None
    assert validate_presentation({
        **base, "data": {"formatted": "2026-10-29", "timezone": 3}
    }) is None
