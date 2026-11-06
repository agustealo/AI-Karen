"""Source-attested tables are runtime projections, not model-authored UI."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime


def _execution(
    *,
    intent="search.general",
    source="tool",
    source_id="web_search",
    allowed_tools=("web_search",),
    allowed_plugins=(),
    success=True,
    degraded=False,
    attempts=None,
    payload=None,
    sources=None,
):
    request = SimpleNamespace(context=SimpleNamespace(
        request_id="req-table-1", correlation_id="corr-table-1",
    ))
    decision = SimpleNamespace(intent=intent)
    plan = SimpleNamespace(
        allowed_tools=allowed_tools, allowed_plugins=allowed_plugins,
    )
    result = SimpleNamespace(
        success=success, degraded=degraded, source=source,
        source_id=source_id,
        attempts=(
            [{"type": source, "id": source_id, "status": "success"}]
            if attempts is None else attempts
        ),
        payload=(
            {"structured_table": {
                "title": "Verified source facts",
                "columns": [
                    {"key": "name", "label": "Name"},
                    {"key": "fact", "label": "Fact"},
                    {"key": "source_url", "label": "Source"},
                ],
                "rows": [{"name": "Reported A", "fact": "Reported B",
                         "source_url": "https://example.org/facts"}],
            }}
            if payload is None else payload
        ),
        sources=([{
            "url": "https://example.org/facts",
            "title": "Reported A",
            "snippet": "Reported B",
        }] if sources is None else sources),
    )
    return request, decision, plan, result


def test_authorized_first_turn_table_projection_and_surface_collection():
    request, decision, plan, result = _execution()
    expected = ChatRuntime._verified_source_table_presentation(
        request, decision, plan, result
    )
    assert expected is not None
    assert expected["component_type"] == "data.table"
    assert expected["evidence_ref"] == "req-table-1:web_search"
    assert expected["correlation_id"] == "corr-table-1"
    assert expected["data"]["rows"] == [
        {"name": "Reported A", "fact": "Reported B",
         "source_url": "https://example.org/facts"}
    ]
    assert ChatRuntime._collect_authorized_surface_parts(
        request, [(decision, plan, result)]
    ) == [expected]


@pytest.mark.parametrize("overrides", [
    {"intent": "chat.general"},
    {"source": "model"},
    {"success": False},
    {"degraded": True},
    {"allowed_tools": ()},
    {"source_id": "other_search"},
    {"attempts": []},
    {"attempts": [{"type": "tool", "id": "web_search", "status": "failed"}]},
    {"attempts": [{"type": "plugin", "id": "web_search", "status": "success"}]},
    {"payload": {"presentation": {"component_type": "data.table"}}},
    {"payload": {"structured_table": {
        "title": "Official guaranteed prices",
        "columns": [
            {"key": "name", "label": "Price: $1,000,000"},
            {"key": "fact", "label": "Fact"},
            {"key": "source_url", "label": "Source"},
        ],
        "rows": [{"name": "Reported A", "fact": "Reported B",
                  "source_url": "https://example.org/facts"}],
    }}},
    {"payload": {"structured_table": {
        "columns": [
            {"key": "name", "label": "Name"},
            {"key": "fact", "label": "Fact"},
            {"key": "source_url", "label": "Source"},
        ],
        "rows": [{"name": "Reported B", "fact": "Reported A",
                  "source_url": "https://example.org/facts"}],
    }}},

    {"sources": []},
    {"sources": [{"url": "https://example.org/else",
                  "title": "Reported A", "snippet": "Reported B"}]},
    {"sources": [{"url": "https://example.org/facts",
                  "title": "Reported A", "snippet": "Different fact"}]},
    {"payload": {"structured_table": {
        "columns": [{"key": "name", "label": "Name"},
                    {"key": "fact", "label": "Fact"},
                    {"key": "source_url", "label": "Source"}],
        "rows": [{"name": "Invented", "fact": "Reported B",
                  "source_url": "https://example.org/facts"}],
    }}},
    {"payload": {"structured_table": {
        "columns": [{"key": "fact", "label": "Fact"}],
        "rows": [{"fact": "Visible", "private": "Forbidden"}],
    }}},
    {"payload": {"structured_table": {
        "columns": [{"key": "fact", "label": "Fact"}],
        "rows": [{"fact": "Visible"}],
        "action": "delete",
    }}},
])
def test_denied_untrusted_or_malformed_table_cannot_be_presented(overrides):
    request, decision, plan, result = _execution(**overrides)
    assert ChatRuntime._verified_source_table_presentation(
        request, decision, plan, result
    ) is None
    assert ChatRuntime._collect_authorized_surface_parts(
        request, [(decision, plan, result)]
    ) == []


def test_authorized_plugin_receipt_uses_existing_gate():
    request, decision, plan, result = _execution(
        source="plugin", allowed_tools=(), allowed_plugins=("web_search",),
    )
    assert ChatRuntime._verified_source_table_presentation(
        request, decision, plan, result
    ) is not None
    plan.allowed_plugins = ()
    assert ChatRuntime._verified_source_table_presentation(
        request, decision, plan, result
    ) is None


def test_stale_tool_presentation_metadata_cannot_override_runtime_provenance():
    request, decision, plan, result = _execution()
    result.payload["presentation"] = {
        "component_type": "data.table",
        "evidence_ref": "another-user",
        "correlation_id": "another-conversation",
    }
    checked = ChatRuntime._verified_source_table_presentation(
        request, decision, plan, result
    )
    assert checked is not None
    assert checked["evidence_ref"] == "req-table-1:web_search"
    assert checked["correlation_id"] == "corr-table-1"

def test_table_cannot_combine_facts_from_distinct_receipts():
    request, decision, plan, result = _execution(
        sources=[
            {"url": "https://example.org/a", "title": "A", "snippet": "A fact"},
            {"url": "https://example.org/b", "title": "B", "snippet": "B fact"},
        ],
        payload={"structured_table": {
            "columns": [
                {"key": "name", "label": "Name"},
                {"key": "fact", "label": "Fact"},
                {"key": "source_url", "label": "Source"},
            ],
            "rows": [{"name": "A", "fact": "B fact",
                      "source_url": "https://example.org/a"}],
        }},
    )
    assert ChatRuntime._verified_source_table_presentation(
        request, decision, plan, result
    ) is None


def test_source_table_does_not_invent_unknown_data_on_missing_cells():
    request, decision, plan, result = _execution()
    result.payload["structured_table"]["rows"][0]["fact"] = None
    projected = ChatRuntime._verified_source_table_presentation(
        request, decision, plan, result
    )
    assert projected is not None
    assert projected["data"]["rows"][0]["fact"] is None

@pytest.mark.parametrize("prompt", [
    "Show latest releases in a table",
    "Tabulate the latest movie sources",
    "Give me a tabular list of recent web sources",
])
def test_first_prompt_explicit_source_table_uses_only_verified_search_results(prompt):
    request, decision, plan, result = _execution(payload={})
    request.messages = [{"role": "user", "content": prompt}]
    result.sources = [
        {"url": "https://example.org/a", "title": "Publisher A",
         "snippet": "Reported headline A"},
        {"url": "https://example.org/b", "title": "Publisher B",
         "snippet": "Reported headline B"},
    ]
    projected = ChatRuntime._verified_source_table_presentation(
        request, decision, plan, result
    )
    assert projected is not None
    assert projected["data"]["title"] == "Verified search source excerpts"
    assert projected["data"]["rows"] == [
        {"source_title": "Publisher A", "source_excerpt": "Reported headline A",
         "source_url": "https://example.org/a"},
        {"source_title": "Publisher B", "source_excerpt": "Reported headline B",
         "source_url": "https://example.org/b"},
    ]
    assert ChatRuntime._collect_authorized_surface_parts(
        request, [(decision, plan, result)]
    ) == [projected]


def test_regular_search_keeps_original_search_cards():
    request, decision, plan, result = _execution(payload={})
    request.messages = [{"role": "user", "content": "latest movies"}]
    assert ChatRuntime._verified_source_table_presentation(
        request, decision, plan, result
    ) is None
    surfaces = ChatRuntime._collect_authorized_surface_parts(
        request, [(decision, plan, result)]
    )
    assert len(surfaces) == 1
    assert surfaces[0]["component_type"] == "search.results"


@pytest.mark.parametrize("overrides", [
    {"success": False},
    {"degraded": True},
    {"source": "model"},
    {"allowed_tools": ()},
    {"attempts": []},
    {"sources": []},
    {"sources": [{"url": "javascript:alert(1)", "title": "Unsafe", "snippet": "Bad"}]},
])
def test_explicit_source_table_cannot_bypass_receipt_gate(overrides):
    request, decision, plan, result = _execution(payload={}, **overrides)
    request.messages = [{"role": "user", "content": "show as a table"}]
    assert ChatRuntime._verified_source_table_presentation(
        request, decision, plan, result
    ) is None

def test_explicit_table_truncates_only_source_excerpt_from_original_text():
    request, decision, plan, result = _execution(payload={})
    request.messages = [{"role": "user", "content": "show source results in a table"}]
    result.sources = [{
        "url": "https://example.org/long-article",
        "title": "Original source title",
        "snippet": "e" * 300,
    }]
    surface = ChatRuntime._verified_source_table_presentation(
        request, decision, plan, result
    )
    assert surface is not None
    assert surface["data"]["rows"][0]["source_excerpt"] == "e" * 240


def test_unusable_source_url_falls_back_to_verified_search_card():
    request, decision, plan, result = _execution(payload={})
    request.messages = [{"role": "user", "content": "table of sources"}]
    result.sources = [{
        "url": "https://example.org/" + "p" * 250,
        "title": "Published title",
        "snippet": "Published excerpt",
    }]
    assert ChatRuntime._verified_source_table_presentation(
        request, decision, plan, result
    ) is None
    surfaces = ChatRuntime._collect_authorized_surface_parts(
        request, [(decision, plan, result)]
    )
    assert len(surfaces) == 1
    assert surfaces[0]["component_type"] == "search.results"

def test_explicit_table_utf16_excerpt_bounds_preserve_source_prefix():
    request, decision, plan, result = _execution(payload={})
    request.messages = [{"role": "user", "content": "latest movies in a table"}]
    result.sources = [{
        "url": "https://example.org/unicode",
        "title": "Publisher",
        "snippet": "🔎" * 121,
    }]
    table = ChatRuntime._verified_source_table_presentation(
        request, decision, plan, result
    )
    assert table is not None
    excerpt = table["data"]["rows"][0]["source_excerpt"]
    assert excerpt == "🔎" * 120
    assert result.sources[0]["snippet"].startswith(excerpt)


def test_untrusted_source_title_is_not_presented_as_a_factual_claim():
    request, decision, plan, result = _execution()
    result.payload["structured_table"]["title"] = "Guaranteed best product on Earth"
    surface = ChatRuntime._verified_source_table_presentation(
        request, decision, plan, result
    )
    assert surface is not None
    assert surface["data"]["title"] == "Verified search source excerpts"


def test_source_title_must_not_be_misrepresented_as_an_excerpt():
    request, decision, plan, result = _execution(
        payload={"structured_table": {
            "columns": [
                {"key": "source_excerpt", "label": "Source excerpt"},
                {"key": "source_url", "label": "Source URL"},
            ],
            "rows": [{"source_excerpt": "Reported A",
                      "source_url": "https://example.org/facts"}],
        }}
    )
    assert ChatRuntime._verified_source_table_presentation(
        request, decision, plan, result
    ) is None
