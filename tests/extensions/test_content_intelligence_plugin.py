"""Content Intelligence is a standalone, stateless and bounded extension."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "src/ai_karen_engine/extensions/plugins/content-intelligence"
SPEC = importlib.util.spec_from_file_location("content_intelligence_engine", PLUGIN / "engine.py")
assert SPEC and SPEC.loader
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)


def _documents():
    return [
        {"id": "a", "name": "Plan", "text": "Alpha delivery depends on Vendor.
Budget approved."},
        {"id": "b", "name": "Notes", "text": "Vendor delivery status pending.
Alpha owner notified."},
    ]


def test_manifest_is_standalone_disabled_and_no_permissions():
    manifest = json.loads((PLUGIN / "plugin_manifest.json").read_text(encoding="utf-8"))
    assert manifest["entrypoint"] == "handler:MainExtension"
    assert manifest["rbac"]["default_enabled"] is False
    assert manifest["permissions"]["memory_read"] is False
    assert manifest["permissions"]["memory_write"] is False
    assert manifest["permissions"]["network_access"] == []
    assert manifest["execution_input_schema"]["additional_properties"] is False


def test_analyze_has_source_fingerprints_and_lexical_hints():
    result = engine.execute({"operation": "analyze", "documents": _documents()})
    assert result["persisted"] is False
    assert len(result["documents"][0]["sha256"]) == 64
    assert result["relationships"][0]["relationship"] == "shared_terms"
    assert "vendor" in result["relationships"][0]["terms"]


def test_search_returns_real_excerpts_and_offsets():
    result = engine.execute({"operation": "search", "documents": _documents(), "query": "vendor delivery"})
    assert result["matches"]
    assert result["matches"][0]["offset"] >= 0
    assert result["search_semantics"] == "lexical_evidence_only"
    assert all(hit["document_id"] in {"a", "b"} for hit in result["matches"])


def test_compare_is_deterministic_and_not_a_semantic_claim():
    params = {"operation": "compare", "documents": _documents(), "left_id": "a", "right_id": "b"}
    result = engine.execute(params)
    assert result == engine.execute(params)
    assert "vendor" in result["shared_terms"]
    assert result["comparison_semantics"] == "lexical_not_semantic"


@pytest.mark.parametrize("params", [
    {"operation": "search", "documents": _documents()},
    {"operation": "analyze", "documents": []},
    {"operation": "analyze", "documents": [_documents()[0]] * 2},
    {"operation": "analyze", "documents": [{"id": "a", "name": "x", "text": "x", "path": "/etc/passwd"}]},
    {"operation": "compare", "documents": _documents(), "left_id": "a", "right_id": "a"},
    {"operation": "analyze", "documents": _documents(), "unexpected": "field"},
    {"operation": "analyze", "documents": [{"id": "x", "name": "x", "text": "z" * 100001}]},
])
def test_bad_inputs_fail_closed(params):
    with pytest.raises(ValueError):
        engine.execute(params)


def test_no_file_io_or_external_sdk_dependency():
    source = (PLUGIN / "engine.py").read_text(encoding="utf-8")
    assert "llama_index" not in source
    assert "open(" not in source
    assert "requests" not in source
