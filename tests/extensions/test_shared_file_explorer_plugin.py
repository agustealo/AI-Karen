"""Tests for the standalone, reusable File Explorer contract."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "src/ai_karen_engine/extensions/plugins/file-explorer"
SPEC = importlib.util.spec_from_file_location("shared_file_explorer_engine", PLUGIN / "engine.py")
assert SPEC and SPEC.loader
ENGINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ENGINE)


def _inventory():
    return [
        {"source_id": "folder-one", "parent_id": None, "kind": "folder",
         "name": "Project", "revision": "r1", "size_bytes": 0, "sha256": None},
        {"source_id": "document-one", "parent_id": "folder-one", "kind": "file",
         "name": "Notes", "revision": "r2", "size_bytes": 18, "sha256": "a" * 64},
    ]


def test_manifest_disabled_and_no_content_permissions():
    m = json.loads((PLUGIN / "plugin_manifest.json").read_text(encoding="utf-8"))
    assert m["name"] == "file-explorer"
    assert m["rbac"]["default_enabled"] is False
    assert not m["permissions"]["memory_read"]
    assert not m["permissions"]["user_data_read"]
    assert m["permissions"]["network_access"] == []
    assert m["execution_input_schema"]["additional_properties"] is False


def test_list_hierarchy_over_host_inventory():
    root = ENGINE.execute({"operation": "list"}, _inventory())
    assert [item["source_id"] for item in root["items"]] == ["folder-one"]
    children = ENGINE.execute({"operation": "list", "parent_id": "folder-one"}, _inventory())
    assert [item["source_id"] for item in children["items"]] == ["document-one"]
    assert children["persisted"] is False


def test_select_returns_refs_not_file_data():
    result = ENGINE.execute({"operation": "select", "source_ids": ["document-one"]}, _inventory())
    assert result["selections"] == [
        {"source_id": "document-one", "revision": "r2", "kind": "file", "sha256": "a" * 64}
    ]
    assert result["source_ref_semantics"] == "reference_only_revalidate_at_consumer"


@pytest.mark.parametrize("params", [
    {"operation": "select", "source_ids": ["missing"]},
    {"operation": "list", "parent_id": "missing"},
    {"operation": "list", "parent_id": "../another-tenant"},
])
def test_unknown_or_traversal_references_fail(params):
    with pytest.raises((ValueError, PermissionError)):
        ENGINE.execute(params, _inventory())


def test_caller_cannot_insert_inventory_into_request():
    with pytest.raises(ValueError):
        ENGINE.execute({"operation": "list", "entries": _inventory()}, _inventory())


def test_duplicate_and_malformed_host_inventory_fail():
    with pytest.raises(ValueError):
        ENGINE.execute({"operation": "list"}, _inventory() * 2)
    with pytest.raises(ValueError):
        ENGINE.execute({"operation": "list"}, [{"source_id": "file", "path": "/etc/passwd"}])


def test_selection_limit_and_input_validation():
    with pytest.raises(ValueError):
        ENGINE.execute({"operation": "select", "source_ids": []}, _inventory())
    with pytest.raises(ValueError):
        ENGINE.execute({"operation": "select", "source_ids": ["document-one", "document-one"]}, _inventory())


def test_no_open_or_network_access_in_engine():
    source = (PLUGIN / "engine.py").read_text(encoding="utf-8")
    assert "open(" not in source
    assert "llama_index" not in source
    assert "requests" not in source
