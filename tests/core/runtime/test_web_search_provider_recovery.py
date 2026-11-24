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


@pytest.mark.asyncio
async def test_search_transport_reservations_share_original_meter():
    from ai_karen_engine.core.runtime.contracts import ExecutionBudget, ExecutionBudgetMeter

    meter = ExecutionBudgetMeter(ExecutionBudget(max_external_requests=1))
    await WebSearchClient._reserve_transport({"execution_meter": meter})
    with pytest.raises(PermissionError, match="budget exhausted"):
        await WebSearchClient._reserve_transport({"execution_meter": meter})
    assert meter.external_requests == 1


@pytest.mark.asyncio
async def test_search_transport_rejects_untyped_meter():
    with pytest.raises(PermissionError, match="Invalid external execution meter"):
        await WebSearchClient._reserve_transport({"execution_meter": object()})


@pytest.mark.asyncio
async def test_governed_searxng_retry_does_not_follow_redirect_or_exceed_quota():
    from unittest.mock import MagicMock

    from ai_karen_engine.core.runtime.contracts import ExecutionBudget, ExecutionBudgetMeter

    meter = ExecutionBudgetMeter(ExecutionBudget(max_external_requests=1))
    registry = SimpleNamespace(get_config=lambda name: {
        "instances": ["https://one.example", "https://two.example"],
    })
    client = WebSearchClient(registry=registry)
    session = MagicMock()
    session.get.return_value.__aenter__.return_value = SimpleNamespace(status=302)
    client.session = session

    result = await client._search_searxng("release notes", 3, execution_meter=meter)

    assert not result.results
    assert meter.external_requests == 1
    session.get.assert_called_once()
    assert session.get.call_args.kwargs["allow_redirects"] is False


def test_legacy_transport_redirect_behavior_is_unchanged():
    assert WebSearchClient._transport_options({}) == {}
