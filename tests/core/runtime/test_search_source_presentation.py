"""A source list is a projection of a completed authorized search, not model output."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.presentation_contract import validate_presentation


def _context():
    return SimpleNamespace(context=SimpleNamespace(
        request_id="request-1", correlation_id="corr-1",
    ))


def _result(*, source="tool", source_id="web_search", success=True,
            degraded=False, attempts=None, sources=None):
    return SimpleNamespace(
        success=success, degraded=degraded, source=source, source_id=source_id,
        attempts=attempts if attempts is not None else [{
            "id": source_id, "type": source, "status": "success",
        }],
        sources=sources if sources is not None else [{
            "url": "https://example.org/news/story",
            "title": "A provider-reported headline",
            "snippet": "An excerpt returned by the search tool.",
            "published_at": "2026-11-05T10:30:00Z",
            "private_token": "never expose",
        }],
    )


def _project(result=None, *, allowed_tools=("web_search",),
             allowed_plugins=(), intent="search.general"):
    return ChatRuntime._verified_search_sources_presentation(
        _context(), SimpleNamespace(intent=intent),
        SimpleNamespace(allowed_tools=allowed_tools, allowed_plugins=allowed_plugins),
        result or _result(),
    )


def test_search_sources_surface_has_complete_authorized_receipt_and_no_secrets():
    rendered = _project()
    assert rendered is not None
    assert rendered["component_type"] == "search.source_list"
    assert rendered["evidence_ref"] == "request-1:web_search"
    assert rendered["correlation_id"] == "corr-1"
    assert rendered["data"] == {"items": [{
        "url": "https://example.org/news/story",
        "title": "A provider-reported headline",
        "snippet": "An excerpt returned by the search tool.",
        "published_at": "2026-11-05T10:30:00Z",
    }]}
    assert "never expose" not in repr(rendered)
    assert ChatRuntime._collect_authorized_surface_parts(_context(), [
        (SimpleNamespace(intent="search.general"),
         SimpleNamespace(allowed_tools=("web_search",), allowed_plugins=()),
         _result()),
    ]) == [rendered]


@pytest.mark.parametrize("mutations", [
    {"success": False}, {"degraded": True}, {"source": "model"},
    {"source": "capability_unavailable"},
    {"attempts": [{"type": "tool", "id": "web_search", "status": "failed"}]},
    {"attempts": [{"type": "tool", "id": "foreign", "status": "success"}]},
    {"attempts": []},
])
def test_missing_or_untrusted_tool_proof_refuses_source_cards(mutations):
    assert _project(_result(**mutations)) is None


def test_search_intent_and_plugin_gate_are_strict():
    assert _project(intent="general.chat") is None
    assert _project(intent="search.weather") is None
    assert _project(allowed_tools=()) is None
    plugin = _result(source="plugin", source_id="intelligent-search")
    assert _project(plugin) is None
    assert _project(plugin, allowed_plugins=("intelligent-search",)) is not None
    assert _project(plugin, allowed_tools=("intelligent-search",)) is None


@pytest.mark.parametrize("url", [
    "http://example.org/story", "javascript:alert(1)",
    "https://127.0.0.1/secret", "https://localhost/p", "https://router.local/x",
    "https://user:password@example.org/a", "https://example.org:8080/internal",
    "https://example.org/a\nscript", "https://[::1]/",
])
def test_unsafe_source_destinations_never_render(url):
    assert _project(_result(sources=[{
        "url": url, "title": "Untrusted", "snippet": "Untrusted link",
    }])) is None


def test_unknown_publication_date_is_omitted_not_fabricated():
    rendered = _project(_result(sources=[{
        "url": "https://example.org/film", "title": "New film announcement",
        "snippet": "A report about a film", "published_at": "yesterday",
    }]))
    assert rendered is not None
    assert rendered["data"]["items"][0] == {
        "url": "https://example.org/film",
        "title": "New film announcement", "snippet": "A report about a film",
    }


def test_discard_invalid_records_and_keep_valid_deduplicated_sources():
    rendered = _project(_result(sources=[
        {"url": "https://127.0.0.1/private", "snippet": "not safe"},
        {"url": "https://example.org/news", "snippet": "Provider excerpt"},
        {"url": "https://example.org/news", "snippet": "Duplicated"},
        {"url": "https://example.net/report", "content": "Retrieved content"},
        {"url": "https://example.net/empty"},
    ]))
    assert rendered is not None
    assert [item["url"] for item in rendered["data"]["items"]] == [
        "https://example.org/news", "https://example.net/report",
    ]
    assert rendered["data"]["items"][1]["snippet"] == "Retrieved content"


def test_rejects_unknown_fields_oversize_or_mismatched_evidence():
    base = _project()
    assert base is not None
    bad = [
        {**base, "data": {"items": [{
            **base["data"]["items"][0], "private_html": "<script>alert(1)</script>",
        }]}},
        {**base, "data": {"items": [{
            **base["data"]["items"][0], "snippet": "x" * 501,
        }]}},
        {**base, "data": {"items": base["data"]["items"] * 7}},
        {**base, "data": {"items": []}},
    ]
    assert all(validate_presentation(item) is None for item in bad)
    assert ChatRuntime._collect_authorized_surface_parts(_context(), [
        (SimpleNamespace(intent="search.general"),
         SimpleNamespace(allowed_tools=("web_search",), allowed_plugins=()),
         _result()),
    ])[0]["evidence_ref"] == "request-1:web_search"


def test_search_does_not_invent_surface_without_sources():
    assert _project(_result(sources=[])) is None
    assert _project(_result(sources=[{"snippet": "No URL"}])) is None
