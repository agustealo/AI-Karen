"""Canonical observation validation rejects invented conditions and unit claims."""

import pytest

from ai_karen_engine.services.response.response_validator import ResponseValidator


@pytest.mark.parametrize("text,reason", [
    ("It is 54.3 degrees Fahrenheit.", "unsupported_temperature_unit"),
    ("It will rain tomorrow.", "unsupported_forecast"),
    ("It is sunny.", "unsupported_weather_condition"),
    ("The humidity is 88%.", "unverified_observation_number"),
])
def test_weather_adversarial_claims(text, reason):
    evidence = {
        "location": "NYC", "temperature": 54.3, "humidity": 47,
        "observed_at": "2026-10-22T10:30",
    }
    verdict = ResponseValidator().validate_observation(text, "search.weather", evidence)
    assert not verdict.valid
    assert verdict.reason == reason


def test_valid_observation_preserved():
    evidence = {"location": "NYC", "temperature": 54.3, "humidity": 47}
    assert ResponseValidator().validate_observation(
        "It's 54.3 degrees in NYC, humidity 47%.", "search.weather", evidence
    ).valid


def test_timezone_claim_must_match_evidence():
    evidence = {
        "time": "10:30", "date": "2026-10-22", "timezone": "America/New_York"
    }
    verdict = ResponseValidator().validate_observation(
        "It is 10:30 in America/Chicago.", "time.current", evidence
    )
    assert not verdict.valid
    assert verdict.reason == "unsupported_timezone"
