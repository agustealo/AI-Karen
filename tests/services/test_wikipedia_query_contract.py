"""Wikipedia MediaWiki query parameters must be valid for aiohttp."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.services.search.web_search_client import WebSearchClient


class _Response:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self):
        return self.payload


class _Session:
    def __init__(self):
        self.calls = []

    def get(self, url, *, params, headers):
        self.calls.append(dict(params))
        assert all(
            isinstance(value, (str, int, float)) and not isinstance(value, bool)
            for value in params.values()
        )
        if len(self.calls) == 1:
            return _Response({"query": {"search": [{"title": "Clock", "pageid": 5, "snippet": "Time"}]}})
        return _Response({"query": {"pages": {"5": {"extract": "A clock displays time."}}}})


@pytest.mark.asyncio
async def test_wikipedia_search_uses_http_safe_parameters():
    client = WebSearchClient()
    session = _Session()
    client.session = session
    result = await client._search_wikipedia("clock", max_results=1)
    assert result.error is None
    assert result.provider == "wikipedia"
    assert len(result.results) == 1
    assert len(session.calls) == 2
    assert session.calls[1]["exintro"] == "1"
    assert session.calls[1]["explaintext"] == "1"
