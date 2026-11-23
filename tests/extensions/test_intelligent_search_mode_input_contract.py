"""KIS-AUDIT-03: explicit mode inputs and structured schema validation."""

import importlib
from types import SimpleNamespace

import pytest

from ai_karen_engine.services.tooling.internet_capability_service import (
    InternetSearchRequest,
)

plugin = importlib.import_module(
    "ai_karen_engine.extensions.plugins.intelligent-search.handler"
)
WebSearchDispatcher = plugin.WebSearchDispatcher


class PreparedHandler:
    async def prepare(self, query, context):
        return {"query": query, "requested_context": context}


class RecordingService:
    def __init__(self):
        self.calls = []

    async def execute(self, query, config_override=None, context=None):
        self.calls.append((query, config_override, context))
        return {
            "status": "ok",
            "provider": "test-provider",
            "sources": [{"url": "https://example.com/grounded"}],
            "results": [],
        }


def dispatcher(mode):
    value = object.__new__(WebSearchDispatcher)
    value._handlers = {mode: PreparedHandler()}
    value._internet_service = RecordingService()
    value.manifest = SimpleNamespace(name="intelligent-search", settings={})
    return value


@pytest.mark.asyncio
async def test_weather_location_provides_effective_query_to_existing_provider():
    search = dispatcher("weather")
    response = await search.run({
        "mode": "weather", "query": "", "context": {"location": "Detroit, MI"}
    })
    assert response["can_execute"] is True
    assert search._internet_service.calls[0][0] == "weather in Detroit, MI"
    assert search._internet_service.calls[0][1]["mode"] == "weather"


@pytest.mark.asyncio
async def test_stock_ticker_supplies_search_query_not_market_price():
    search = dispatcher("stock_market")
    response = await search.run({
        "mode": "stock_market", "query": "", "context": {"ticker": "AAPL"}
    })
    assert response["can_execute"] is True
    assert search._internet_service.calls[0][0] == "AAPL stock market news"


@pytest.mark.asyncio
async def test_stock_company_name_supplies_search_query():
    search = dispatcher("stock_market")
    response = await search.run({
        "mode": "stock_market", "query": "",
        "context": {"company_name": "Example Holdings"}
    })
    assert response["can_execute"] is True
    assert search._internet_service.calls[0][0] == "Example Holdings stock market news"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,context,status", [
    ("weather", {}, "needs_location"),
    ("stock_market", {}, "needs_query"),
    ("general", {}, "needs_query"),
])
async def test_missing_input_returns_error_without_external_request(
    mode, context, status
):
    search = dispatcher(mode)
    response = await search.run({"mode": mode, "query": "", "context": context})
    assert response["status"] == status
    assert response["success"] is False
    assert response["sources"] == []
    assert response["results"] == []
    assert search._internet_service.calls == []


def test_json_schema_is_normalized_for_existing_runtime_extractor():
    request = InternetSearchRequest.from_payload(
        "extract price",
        {"extraction": {
            "type": "schema",
            "schema": '{"fields":{"price":"USD ([0-9]+)"}}',
        }},
    )
    assert request.extraction["schema"] == {
        "fields": {"price": "USD ([0-9]+)"}
    }


@pytest.mark.parametrize("schema", [
    '{"fields":',
    '"text"',
    "1",
    "x" * 17000,
])
def test_invalid_schema_does_not_silently_skip_extraction(schema):
    with pytest.raises(ValueError, match="Extraction schema"):
        InternetSearchRequest.from_payload(
            "extract price", {"extraction": {"schema": schema}}
        )
