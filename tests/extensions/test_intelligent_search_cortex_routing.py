"""CORTEX's real capability resolver must preserve consumer search intent."""

from ai_karen_engine.core.cortex.routing_intents import resolve_capability_decision


def test_current_weather_question_uses_structured_capability():
    decision = resolve_capability_decision("What's the weather in Detroit?")
    assert decision.intent == "search.weather"
    assert decision.requires_live_data is True


def test_weather_without_location_requires_location_context():
    decision = resolve_capability_decision("What's the weather?")
    assert decision.intent == "search.weather"
    assert "location.current" in decision.missing_requirements


def test_weather_band_is_not_forecast_intent():
    decision = resolve_capability_decision("Weather Report jazz albums")
    assert decision.intent != "search.weather"
