"""Automatic search modes use CORTEX, including direct service calls."""
import pytest
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


@pytest.mark.asyncio
async def test_missing_weather_location_is_input_requirement_not_web_fallback(monkeypatch):
    from unittest.mock import AsyncMock
    from ai_karen_engine.services.search import weather_observation_provider

    service = object.__new__(InternetCapabilityService)
    service.planner = SearchQueryPlanner()
    service._authorize = AsyncMock(return_value=None)

    called = []
    async def missing_location(query):
        called.append(query)
        raise ValueError("Explicit location required for live weather")

    monkeypatch.setattr(weather_observation_provider, "fetch_weather_observation", missing_location)
    result = await service.execute("Whats the weather")
    assert called == ["Whats the weather"]
    assert result["status"] == "needs_location"
    assert result["missing_requirements"] == ["location.current"]
    assert result["provider"] == "open_meteo"
    assert result["sources"] == []
    assert result["metadata"]["degraded"] is False
