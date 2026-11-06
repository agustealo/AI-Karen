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
