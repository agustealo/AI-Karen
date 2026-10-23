"""Observation answers cannot invent links or measurement facts."""

from ai_karen_engine.services.response.response_validator import ResponseValidator


def test_weather_observation_accepts_grounded_answer_without_url():
    result = ResponseValidator().validate_observation(
        "It is 54.3°F and sunny in New York.",
        "search.weather",
        {"temperature_f": 54.3, "conditions": "sunny", "location": "New York"},
    )
    assert result.valid


def test_weather_observation_rejects_invented_url():
    result = ResponseValidator().validate_observation(
        "It is 54.3°F in New York. Source: https://example.org/imaginary",
        "search.weather",
        {"temperature_f": 54.3, "location": "New York"},
    )
    assert not result.valid
    assert result.reason == "unverified_observation_url"


def test_time_observation_rejects_fabricated_source_url():
    result = ResponseValidator().validate_observation(
        "It is 11:14 AM. https://example.org/clock",
        "time.current",
        {"value": "11:14 AM", "timezone": "America/New_York"},
    )
    assert not result.valid
    assert result.reason == "unverified_observation_url"


def test_unverified_numbers_are_rejected():
    result = ResponseValidator().validate_observation(
        "It is 80°F.",
        "search.weather",
        {"temperature_f": 54.3},
    )
    assert not result.valid
    assert result.reason == "unverified_observation_number"


def test_absent_observation_is_rejected():
    result = ResponseValidator().validate_observation(
        "It is sunny.", "search.weather", {}
    )
    assert not result.valid
    assert result.reason == "missing_observation_evidence"
