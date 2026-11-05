"""First-prompt search cards require actual authorized source receipts."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.presentation_contract import validate_presentation


def _run(
    *,
    success=True,
    degraded=False,
    source="tool",
    allowed_tools=("web_search",),
    allowed_plugins=(),
    attempts=None,
    sources=None,
    intent="search.general",
):
    request = SimpleNamespace(context=SimpleNamespace(
        request_id="req-search-1",
        correlation_id="corr-search-1",
    ))
    decision = SimpleNamespace(intent=intent)
    plan = SimpleNamespace(
        allowed_tools=allowed_tools,
        allowed_plugins=allowed_plugins,
    )
    result = SimpleNamespace(
        success=success,
        degraded=degraded,
        source=source,
        source_id="web_search",
        payload={},
        attempts=(
            [{"type": source, "id": "web_search", "status": "success"}]
            if attempts is None else attempts
        ),
        sources=(
            [{
                "title": "Verified public headline",
                "snippet": "Short, provider-reported description.",
                "url": "https://example.org/news",
                "published_at": "2026-11-05T09:00:00Z",
                "private_token": "SECRET",
            }]
            if sources is None else sources
        ),
    )
    return (
        ChatRuntime._verified_search_presentation(request, decision, plan, result),
        request, decision, plan, result,
    )


def test_first_prompt_search_sources_project_into_versioned_envelope():
    envelope, request, decision, plan, result = _run()
    assert envelope is not None
    assert envelope["component_type"] == "search.results"
    assert envelope["evidence_ref"] == "req-search-1:web_search"
    assert envelope["correlation_id"] == "corr-search-1"
    assert envelope["data"]["results"][0]["title"] == "Verified public headline"
    assert "private_token" not in str(envelope)
    assert validate_presentation(envelope) == envelope
    assert ChatRuntime._collect_authorized_surface_parts(
        request, [(decision, plan, result)]
    ) == [envelope]


@pytest.mark.parametrize("override", [
    {"success": False},
    {"degraded": True},
    {"source": "model"},
    {"allowed_tools": ()},
    {"attempts": [{"type": "tool", "id": "web_search", "status": "failed"}]},
    {"attempts": [{"type": "plugin", "id": "web_search", "status": "success"}]},
    {"intent": "search.weather"},
])
def test_denied_or_non_search_result_cannot_create_cards(override):
    assert _run(**override)[0] is None


def test_authorized_plugin_fallback_preserves_same_evidence_rules():
    assert _run(
        source="plugin", allowed_tools=(), allowed_plugins=("web_search",),
    )[0] is not None
    assert _run(source="plugin", allowed_plugins=())[0] is None


def test_only_public_url_excerpts_enter_search_cards():
    sources = [
        {"title": "Invalid", "snippet": "Untrusted", "url": "javascript:alert(1)"},
        {"title": "Local", "snippet": "Do not show", "url": "http://127.0.0.1/private"},
        {"snippet": "No source at all"},
        {
            "title": "Public",
            "snippet": "Verified search excerpt",
            "url": "https://example.org/public",
            "published_at": 1234,
            "access_token": "do-not-include",
        },
        {
            "title": "Duplicate",
            "snippet": "Should not repeat",
            "url": "https://example.org/public",
        },
    ]
    envelope = _run(sources=sources)[0]
    assert envelope is not None
    assert envelope["data"]["results"] == [{
        "url": "https://example.org/public",
        "snippet": "Verified search excerpt",
        "title": "Public",
    }]


@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "file:///etc/passwd",
    "http://localhost:8000",
    "http://127.0.0.1/path",
    "http://192.168.1.1/",
    "https://user:password@example.org/",
    "https://example.org/space here",
])
def test_invalid_or_sensitive_source_urls_fail_closed(url):
    raw = {
        "schema_version": 1,
        "presentation_id": "search-1",
        "component_type": "search.results",
        "evidence_ref": "req-1:web_search",
        "data": {"results": [{"url": url, "snippet": "Test"}]},
    }
    assert validate_presentation(raw) is None


def test_search_schema_rejects_forged_fields_duplicates_and_excess_entries():
    raw = {
        "schema_version": 1, "presentation_id": "search-1",
        "component_type": "search.results", "evidence_ref": "req-1:web_search",
        "data": {"results": [{"url": "https://example.org/a", "snippet": "Evidence"}]},
    }
    assert validate_presentation(raw) is not None
    assert validate_presentation({
        **raw, "data": {"results": [{**raw["data"]["results"][0], "secret": "x"}]},
    }) is None
    assert validate_presentation({
        **raw, "data": {"results": raw["data"]["results"] * 2},
    }) is None
    assert validate_presentation({
        **raw, "data": {"results": [
            {"url": f"https://example.org/{i}", "snippet": "Evidence"}
            for i in range(6)
        ]},
    }) is None
    assert validate_presentation({
        **raw, "data": {"results": [{"url": "https://example.org/a", "snippet": "🌎" * 9000}]},
    }) is None
