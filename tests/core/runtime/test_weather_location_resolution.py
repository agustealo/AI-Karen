"""Weather context recovery uses only explicit or authorized location evidence."""
from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor


def test_weather_explicit_location_takes_priority_over_profile():
    resolver = DirectCapabilityExecutor._weather_query_with_location
    assert resolver(
        "What's the weather in Detroit?",
        {"weather_location": "Chicago"},
    ) == "What's the weather in Detroit?"


def test_weather_location_from_user_selected_context():
    resolver = DirectCapabilityExecutor._weather_query_with_location
    assert resolver("What's the weather?", {"weather_location": "Detroit, MI"}) == (
        "What's the weather in Detroit, MI?"
    )


def test_location_not_guessed_from_unattributed_metadata():
    resolver = DirectCapabilityExecutor._weather_query_with_location
    assert resolver("What's the weather?", {"city": "Detroit"}) is None
    assert resolver("What's the weather?", {"location": "Detroit", "location_source": "inferred"}) is None


def test_consented_profile_location_is_eligible():
    resolver = DirectCapabilityExecutor._weather_query_with_location
    assert resolver(
        "Weather", {"city": "Detroit", "location_source": "user_profile"}
    ) == "Weather in Detroit?"


def test_absent_location_prompts_for_missing_input_without_fabricated_data():
    resolver = DirectCapabilityExecutor._weather_query_with_location
    assert resolver("What's the weather?", {}) is None
