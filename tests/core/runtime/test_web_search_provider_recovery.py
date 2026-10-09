"""Search registry fallback must produce real results, not fake data."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.services.search.web_search_client import (
    SearchResponse,
    SearchResult,
    WebSearchClient,
)


@pytest.mark.asyncio
async def test_web_search_recovers_from_first_provider_without_faking_result():
    registry = SimpleNamespace(
        select_provider=lambda requested=None: "duckduckgo",
        sorted_enabled=lambda: ["duckduckgo", "searxng"],
        get_descriptor=lambda provider: SimpleNamespace(health="unknown"),
    )
    client = WebSearchClient(registry=registry)
    client._search_with_provider = AsyncMock(side_effect=[
        SearchResponse(query="weather", results=[], provider="duckduckgo", error="HTTP 429"),
        SearchResponse(
            query="weather",
            results=[SearchResult(title="Forecast", url="https://example.org/weather", snippet="Forecast data")],
            provider="searxng",
        ),
    ])
    result = await client.search("weather")
    assert result.provider == "searxng"
    assert result.results[0].snippet == "Forecast data"
    assert client._search_with_provider.await_count == 2


@pytest.mark.asyncio
async def test_all_failed_search_providers_report_failure_not_invented_weather():
    registry = SimpleNamespace(
        select_provider=lambda requested=None: "duckduckgo",
        sorted_enabled=lambda: ["duckduckgo", "searxng"],
        get_descriptor=lambda provider: SimpleNamespace(health="unknown"),
    )
    client = WebSearchClient(registry=registry)
    client._search_with_provider = AsyncMock(side_effect=RuntimeError("unreachable"))
    result = await client.search("weather")
    assert result.results == []
    assert result.provider == "none"
    assert "duckduckgo" in result.error
    assert "searxng" in result.error
