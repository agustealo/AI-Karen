"""Regression tests for model-authored live-observation grounding."""

import pytest

from ai_karen_engine.services.response.response_validator import ResponseValidator


@pytest.mark.parametrize(
    ("answer", "intent", "evidence", "reason"),
    [
        ("It is 92 degrees.", "search.weather", {"temperature_f": 54}, "unverified_observation_number"),
        ("It will snow tomorrow.", "search.weather", {"conditions": "clear"}, "unsupported_forecast"),
        ("It is raining.", "search.weather", {"conditions": "clear"}, "unsupported_weather_condition"),
        ("The temperature is 54°C.", "search.weather", {"temperature_f": 54}, "unsupported_temperature_unit"),
        ("It's 11:14 in Europe/Paris.", "time.current", {"value": "11:14", "timezone": "America/Detroit"}, "unsupported_timezone"),
    ],
)
def test_rejects_unsupported_model_observation(answer, intent, evidence, reason):
    verdict = ResponseValidator().validate_observation(answer, intent, evidence)
    assert not verdict.valid
    assert verdict.reason == reason


@pytest.mark.parametrize(
    ("answer", "intent", "evidence"),
    [
        ("It is 54°F and clear.", "search.weather", {"temperature_f": 54, "conditions": "clear"}),
        ("The local time is 11:14 in America/Detroit.", "time.current", {"value": "11:14", "timezone": "America/Detroit"}),
    ],
)
def test_accepts_grounded_model_observation(answer, intent, evidence):
    assert ResponseValidator().validate_observation(answer, intent, evidence).valid



@pytest.mark.parametrize(
    ("answer", "intent", "evidence"),
    [
        (
            "The current time is 10:30 AM. I am using the time.current "
            "continuity candidate, which matches your recurring behavioral patterns.",
            "time.current",
            {"formatted": "10:30 AM", "timezone": "America/Detroit"},
        ),
        (
            "It is 54 degrees and clear. The search.weather continuity "
            "candidate approved this response.",
            "search.weather",
            {"temperature": 54, "conditions": "clear"},
        ),
        (
            "It is 11:14. The authorized execution plan requires it.",
            "time.current",
            {"value": "11:14"},
        ),
    ],
)
def test_model_cannot_leak_internal_routing_even_with_correct_live_numbers(
    answer, intent, evidence,
):
    verdict = ResponseValidator().validate_observation(answer, intent, evidence)
    assert not verdict.valid
    assert verdict.reason == "internal_observation_metadata"
