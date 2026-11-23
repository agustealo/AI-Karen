"""IS-001: one canonical request adapter preserves plugin search restrictions."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.services.tooling.internet_capability_service import (
    InternetCapabilityService,
    InternetSearchRequest,
)


def test_prepared_mode_policies_are_consumed_by_runtime_request():
    prepared = {
        "mode": "news",
        "max_urls": 8,
        "freshness_bias": 0.95,
        "search_profile": {
            "prefer_recent": True,
            "prefer_official_sources": False,
            "allow_forum_results": False,
        },
        "domain_policy": {
            "allowed_domains": ["https://allowed.example", "https://blocked.allowed.example"],
            "blocked_domains": ["blocked.allowed.example"],
        },
        "time_policy": {
            "time_range": "w",
            "published_after": "2026-11-01",
            "published_before": "2026-11-23",
        },
        # Untrusted informational hints must not become the execution identity.
        "context_hints": {"user_id": "spoofed", "tenant_id": "another-tenant"},
    }

    request = InternetSearchRequest.from_payload("release updates", prepared)

    assert request.max_urls == 8
    assert request.freshness_bias == 0.95
    assert request.prefer_recent is True
    assert request.prefer_official_sources is False
    assert request.allow_forum_results is False
    assert request.allowed_domains == ["allowed.example", "blocked.allowed.example"]
    assert request.blocked_domains == ["blocked.allowed.example"]
    assert request.time_range == "w"
    assert request.published_after == "2026-11-01"
    assert request.published_before == "2026-11-23"

    strategy = request.strategy_overrides()
    service = object.__new__(InternetCapabilityService)
    assert service._is_url_allowed("https://allowed.example/page", strategy)
    assert not service._is_url_allowed("https://blocked.allowed.example/page", strategy)
    assert not service._is_url_allowed("https://elsewhere.example/page", strategy)
    assert "context_hints" not in strategy


def test_explicit_top_level_service_options_remain_compatible():
    request = InternetSearchRequest.from_payload(
        "source policy",
        {
            "allowed_domains": ["top.example"],
            "blocked_domains": ["denied.top.example"],
            "time_range": "d",
            "prefer_recent": False,
            "search_profile": {"prefer_recent": True},
            "domain_policy": {"allowed_domains": ["nested.example"]},
            "time_policy": {"time_range": "w"},
        },
    )
    assert request.allowed_domains == ["top.example"]
    assert request.blocked_domains == ["denied.top.example"]
    assert request.time_range == "d"
    assert request.prefer_recent is False


class _SearchClient:
    def __init__(self):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def search(self, *, query, max_results, time_range=None):
        self.calls.append((query, max_results, time_range))
        return SimpleNamespace(
            provider="provider-test",
            results=[
                SimpleNamespace(url="https://denied.allowed.example/item", title="Denied", snippet=""),
                SimpleNamespace(url="https://outside.example/item", title="Outside", snippet=""),
                SimpleNamespace(url="https://allowed.example/item", title="Allowed", snippet=""),
            ],
        )


@pytest.mark.asyncio
async def test_discovery_filters_disallowed_sources_before_crawling():
    client = _SearchClient()
    request = InternetSearchRequest.from_payload(
        "reliable facts",
        {
            "max_urls": 3,
            "domain_policy": {
                "allowed_domains": ["allowed.example", "denied.allowed.example"],
                "blocked_domains": ["denied.allowed.example"],
            },
            "time_policy": {"time_range": "w"},
        },
    )
    service = InternetCapabilityService(search_client=client)
    urls, providers = await service._get_relevant_urls(
        [request.query], request.strategy_overrides(), request, 3
    )

    assert urls == ["https://allowed.example/item"]
    assert providers == ["provider-test"]
    assert client.calls == [("reliable facts", 3, "w")]
