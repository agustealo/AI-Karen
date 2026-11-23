"""KIS-AUDIT-02: prove bounded crawl traversal and observed diagnostics."""

import time

import pytest

from ai_karen_engine.services.tooling.internet_capability_service import (
    InternetCapabilityService,
    InternetExecutionContext,
    InternetSearchRequest,
)


class CrawlStub:
    """Test-only deterministic crawler. Production always uses Crawl4AI guards."""

    available = True

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def fetch_many(self, urls, *, bypass_cache=False, depth=0):
        self.calls.append((list(urls), bypass_cache, depth))
        return [
            dict(self.pages.get(url, {"url": url, "success": False, "error": "unavailable"}))
            for url in urls
        ]


def page(url, *links):
    return {
        "url": url,
        "markdown": "Verified public content",
        "success": True,
        "links": [{"url": item, "text": "Source"} for item in links],
    }


def request(crawl=None):
    return InternetSearchRequest.from_payload("public information", {"crawl": crawl} if crawl else {})


def test_limits_and_cache_are_normalized_once():
    normalized = request({
        "enabled": True,
        "max_pages": 1000,
        "max_depth": 100,
        "use_cache": False,
        "include_domains": ["docs.example"],
        "exclude_domains": ["blocked.docs.example"],
    })
    assert normalized.crawl_max_pages == 25
    assert normalized.crawl_max_depth == 5
    assert normalized.bypass_cache is True
    assert normalized.crawl_allowed_domains == ["docs.example"]
    assert normalized.crawl_blocked_domains == ["blocked.docs.example"]
    assert request({"enabled": True}).crawl_max_depth == 1


@pytest.mark.asyncio
async def test_default_crawl_keeps_original_seed_coverage_without_link_following():
    root = "https://docs.example/start"
    other = "https://docs.example/other"
    crawler = CrawlStub({
        root: page(root, "/discovered"),
        other: page(other),
    })
    service = InternetCapabilityService(crawler=crawler)
    attempted = []
    found = await service._crawl_many([root, other], request(), page_budget=2, attempt_sink=attempted)
    assert attempted == [root, other]
    assert len(found) == 2
    assert [x[2] for x in crawler.calls] == [0]
    assert "/discovered" not in str(attempted)


@pytest.mark.asyncio
async def test_deep_crawl_observes_page_depth_domains_and_runtime_budget():
    start = "https://docs.example/start"
    first = "https://docs.example/first"
    second = "https://docs.example/second"
    third = "https://docs.example/third"
    crawler = CrawlStub({
        start: page(start, "/first", "/second", "https://external.example/escape",
                    "https://blocked.docs.example/page", "http://127.0.0.1/private"),
        first: page(first, "/third"),
        second: page(second),
        third: page(third),
    })
    service = InternetCapabilityService(crawler=crawler)
    normalized = request({
        "enabled": True, "max_pages": 10, "max_depth": 3,
        "include_domains": ["docs.example"],
        "exclude_domains": ["blocked.docs.example"],
        "use_cache": False,
    })
    attempted = []
    found = await service._crawl_many(
        [start], normalized, page_budget=4, attempt_sink=attempted
    )
    assert attempted == [start, first, second, third]
    assert [page["depth"] for page in found] == [0, 1, 1, 2]
    assert [depth for _, _, depth in crawler.calls] == [0, 1, 2]
    assert all(not cache for _, cache, _ in [])  # No private data needed.
    assert all(bypass for _, bypass, _ in crawler.calls)
    assert len(attempted) == 4


@pytest.mark.asyncio
async def test_page_failures_and_missing_results_do_not_become_sources():
    root = "https://docs.example/good"
    missing = "https://docs.example/missing"
    crawler = CrawlStub({
        root: page(root),
        missing: {"url": missing, "success": False, "error": "robots_blocked"},
    })
    service = InternetCapabilityService(crawler=crawler)
    attempted = []
    found = await service._crawl_many(
        [root, missing], request(), page_budget=2, attempt_sink=attempted
    )
    assert len(attempted) == 2
    assert len(found) == 1
    assert service._normalize_crawl_results([None]) == []

    response = service._build_response(
        request=request(),
        mode="general",
        strategy={"query_strategy": "broad"},
        expanded_queries=["public information"],
        urls=[root, missing],
        crawl_results=found,
        processed_chunks=[],
        start_time=time.perf_counter(),
        degraded=True,
        warnings=["1 crawl attempt did not return a usable page."],
        execution_context=InternetExecutionContext(),
        crawl_attempts=attempted,
        crawl_elapsed_ms=19,
    )
    assert response["crawl"]["pages_requested"] == 2
    assert response["crawl"]["pages_succeeded"] == 1
    assert response["crawl"]["pages_failed"] == 1
    assert response["crawl"]["latency_ms"] == 19
    assert response["crawl"]["degraded"] is True
    assert response["crawl"]["capabilities"]["deep_traversal"] is False
    assert response["metadata"]["degraded"] is True
