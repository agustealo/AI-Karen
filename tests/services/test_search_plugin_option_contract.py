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
    assert not service._is_url_allowed("https://blocked.allowed.example:443/page", strategy)
    assert not service._is_url_allowed("https://someone@blocked.allowed.example/page", strategy)
    assert not service._is_url_allowed("https://elsewhere.example/page", strategy)
    assert not service._is_url_allowed("https:///missing-host", strategy)
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


@pytest.mark.asyncio
async def test_web_search_tool_preserves_declared_retrieval_restrictions():
    from unittest.mock import AsyncMock

    from ai_karen_engine.services.tooling.tool_service import ToolInput
    from ai_karen_engine.tools.web_search_tool import WebSearchTool

    tool = WebSearchTool()
    service = SimpleNamespace(execute=AsyncMock(return_value={"results": []}))
    tool._service = service
    result = await tool.execute(ToolInput(
        tool_name="web_search",
        parameters={
            "query": "release notes",
            "mode": "docs",
            "max_urls": 3,
            "allowed_domains": ["example.org"],
            "blocked_domains": ["private.example.org"],
            "time_range": "w",
            "prefer_recent": False,
        },
    ))
    assert result.success
    options = service.execute.await_args.kwargs["config_override"]
    request = InternetSearchRequest.from_payload("release notes", options)
    assert request.allowed_domains == ["example.org"]
    assert request.blocked_domains == ["private.example.org"]
    assert request.time_range == "w"
    assert request.prefer_recent is False
    assert request.max_urls == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("parameters", [
    {"allowed_domains": [" "]},
    {"blocked_domains": [42]},
    {"mode": "weather", "allowed_domains": ["example.org"]},
])
async def test_web_search_tool_rejects_unsupported_or_invalid_restrictions(parameters):
    from unittest.mock import AsyncMock

    from ai_karen_engine.services.tooling.tool_service import ToolInput
    from ai_karen_engine.tools.web_search_tool import WebSearchTool

    tool = WebSearchTool()
    service = SimpleNamespace(execute=AsyncMock())
    tool._service = service
    result = await tool.execute(ToolInput(
        tool_name="web_search",
        parameters={"query": "release notes", **parameters},
    ))
    assert not result.success
    service.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["general", "weather"])
async def test_zero_external_budget_blocks_search_and_weather_before_network(mode):
    from unittest.mock import AsyncMock

    from ai_karen_engine.core.runtime.contracts import ExecutionContext

    service = InternetCapabilityService()
    service._get_relevant_urls = AsyncMock()
    context = ExecutionContext(
        request_id="budget-test",
        correlation_id="budget-test",
        user_id="test-user",
        tenant_id="test-tenant",
        allowed_capabilities=["web.search"],
        budget=SimpleNamespace(max_external_requests=0),
    )
    from ai_karen_engine.services.search import weather_observation_provider
    from unittest.mock import patch

    with patch.object(weather_observation_provider, "fetch_weather_observation", new_callable=AsyncMock) as weather:
        result = await service.execute(
            "weather in Detroit" if mode == "weather" else "release notes",
            config_override={"mode": mode},
            context=context,
        )
        weather.assert_not_awaited()
    service._get_relevant_urls.assert_not_awaited()
    assert result["status"] == "permission_denied"
    assert not result.get("sources")
    assert not result.get("results")


def test_zero_external_budget_does_not_force_a_source():
    service = object.__new__(InternetCapabilityService)
    request = InternetSearchRequest.from_payload("release notes", {"max_urls": 5})
    assert service._effective_max_urls(
        {}, request, SimpleNamespace(max_external_requests=0)
    ) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1])
async def test_nonpositive_acquisition_limits_do_not_start_io(limit):
    from unittest.mock import AsyncMock, Mock

    service = object.__new__(InternetCapabilityService)
    service._resolve_search_client = Mock()
    service.crawler = SimpleNamespace(fetch_many=AsyncMock(), fetch_url=AsyncMock())
    request = InternetSearchRequest.from_payload("release notes", {})
    urls = ["https://example.org/release"]
    attempts = []
    assert await service._get_relevant_urls(
        [request.query], {}, request, limit
    ) == ([], [])
    assert service._select_domain_diverse_urls(urls, limit) == []
    assert await service._crawl_many(
        urls, request, page_budget=limit, attempt_sink=attempts
    ) == []
    assert attempts == []
    service._resolve_search_client.assert_not_called()
    service.crawler.fetch_many.assert_not_awaited()
    service.crawler.fetch_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_governed_crawl_rejects_unmetered_adapter():
    from unittest.mock import AsyncMock

    from ai_karen_engine.core.runtime.contracts import ExecutionBudget, ExecutionBudgetMeter

    meter = ExecutionBudgetMeter(ExecutionBudget(max_external_requests=2))
    service = object.__new__(InternetCapabilityService)
    service.crawler = SimpleNamespace(fetch_many=AsyncMock(return_value=[]))
    request = InternetSearchRequest.from_payload("release notes", {})
    with pytest.raises(PermissionError, match="Crawler cannot enforce"):
        await service._crawl_many(
            ["https://example.org/one"], request, page_budget=2, execution_meter=meter
        )
    service.crawler.fetch_many.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_tool_rejects_unbound_meter_before_service():
    from unittest.mock import AsyncMock

    from ai_karen_engine.core.runtime.contracts import ExecutionBudget, ExecutionBudgetMeter
    from ai_karen_engine.services.tooling.tool_service import ToolInput
    from ai_karen_engine.tools.web_search_tool import WebSearchTool

    tool = WebSearchTool()
    service = SimpleNamespace(execute=AsyncMock())
    tool._service = service
    result = await tool.execute(ToolInput(
        tool_name="web_search",
        parameters={"query": "release notes"},
        user_context={"execution_meter": ExecutionBudgetMeter(ExecutionBudget())},
    ))
    assert not result.success
    service.execute.assert_not_awaited()
