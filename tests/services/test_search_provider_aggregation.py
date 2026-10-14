"""Web search must preserve configured provider authority while diversifying results."""

import pytest
from unittest.mock import AsyncMock

from ai_karen_engine.services.search.web_search_client import (
    SearchResponse, SearchResult, WebSearchClient,
)
from ai_karen_engine.services.search.web_search_provider_registry import WebSearchProviderRegistry


def item(url):
    return SearchResult(title=url, url=url, snippet="Relevant source")


@pytest.mark.asyncio
async def test_general_search_aggregates_hosts_across_providers():
    registry = WebSearchProviderRegistry(settings={"search": {
        "duckduckgo": {"enabled": True, "priority": 100},
        "searxng": {"enabled": True, "priority": 95},
        "wikipedia": {"enabled": True, "priority": 85},
        "brave_search_free": {"enabled": False},
        "mojeek": {"enabled": False},
        "startpage": {"enabled": False},
    }})
    client = WebSearchClient(settings={"aggregation": {
        "max_providers": 3, "min_distinct_hosts": 3,
    }}, registry=registry)
    async def dispatch(name, query, maximum, time_range, **kwargs):
        data = {
            "duckduckgo": [item("https://example.com/one"), item("https://example.com/two")],
            "searxng": [item("https://museum.org/history")],
            "wikipedia": [item("https://en.wikipedia.org/wiki/History_of_Jamaica")],
        }
        return SearchResponse(query=query, results=data.get(name, []), provider=name)
    client._search_with_provider = AsyncMock(side_effect=dispatch)

    result = await client.search("Jamaican History", max_results=3)
    assert len(result.results) == 3
    assert {x.url.split("/")[2] for x in result.results} == {
        "example.com", "museum.org", "en.wikipedia.org"
    }
    assert "wikipedia" in result.provider


@pytest.mark.asyncio
async def test_explicit_provider_remains_pinned():
    registry = WebSearchProviderRegistry()
    client = WebSearchClient(registry=registry)
    client._search_with_provider = AsyncMock(return_value=SearchResponse(
        query="Jamaica", provider="wikipedia",
        results=[item("https://en.wikipedia.org/wiki/Jamaica")],
    ))
    response = await client.search("Jamaica", provider="wikipedia")
    assert response.results
    assert client._search_with_provider.await_count == 1
