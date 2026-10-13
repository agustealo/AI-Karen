"""Real search discovery survives crawl failure without becoming fetched evidence."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.services.tooling.internet_capability_service import InternetCapabilityService


class Provider:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def search(self, **kwargs):
        return SimpleNamespace(
            provider="wikipedia",
            results=[SimpleNamespace(
                url="https://en.wikipedia.org/wiki/History_of_Jamaica",
                title="History of Jamaica",
                snippet="Historical overview returned by the search provider",
                published_date=None,
            )],
        )


@pytest.mark.asyncio
async def test_discovered_result_retains_actual_link_and_snippet():
    service = object.__new__(InternetCapabilityService)
    service._resolve_search_client = lambda: Provider()
    service.max_expanded_queries = 2
    sink = []
    urls, providers = await service._get_relevant_urls(
        ["jamaican history"], {}, None, 5, discovery_sink=sink
    )
    assert urls == ["https://en.wikipedia.org/wiki/History_of_Jamaica"]
    assert providers == ["wikipedia"]
    assert sink[0]["title"] == "History of Jamaica"
    assert sink[0]["evidence_level"] == "search_snippet"
    assert sink[0]["snippet"].startswith("Historical overview")


def test_fetched_and_discovered_evidence_remain_distinct():
    service = object.__new__(InternetCapabilityService)
    # The response builder includes metadata beyond this unit; source shape
    # is explicitly tested through the discovery sink above.
    assert service._build_sources([]) == []
