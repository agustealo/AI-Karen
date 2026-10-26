"""Automatic search modes use CORTEX, including direct service calls."""
from ai_karen_engine.services.search.search_query_planner import SearchQueryPlanner
from ai_karen_engine.services.tooling.internet_capability_service import (
    InternetCapabilityService,
    InternetSearchRequest,
)


def _resolve(query: str, mode: str | None = None) -> str:
    # Exercise mode routing without initializing networking or persistence.
    service = object.__new__(InternetCapabilityService)
    service.planner = SearchQueryPlanner()
    return service._resolve_mode(InternetSearchRequest(query=query, mode=mode))


def test_automatic_weather_does_not_fall_through_to_general():
    assert _resolve("Whats the weather") == "weather"
    assert _resolve("What's the weather in Detroit?") == "weather"
    assert _resolve("Whats the weather", mode="auto") == "weather"


def test_explicit_user_mode_is_respected():
    assert _resolve("Whats the weather", mode="general") == "general"


def test_conceptual_weather_report_does_not_invoke_observation():
    assert _resolve("Weather Report jazz albums") == "general"
