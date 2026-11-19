"""Pure shared explorer projection over a trusted, bounded host inventory.

The host owns resource discovery and authorization. This module refuses
arbitrary paths, never reads user files and never grants access based on labels.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

MAX_ITEMS = 200
MAX_SELECTION = 24
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
HEX64 = re.compile(r"^[a-f0-9]{64}$")
FIELDS = {"source_id", "parent_id", "kind", "name", "revision", "size_bytes", "sha256"}


def _identifier(value: Any, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value) or value in {".", ".."}:
        raise ValueError("file_explorer_identifier_invalid")
    return value


def _inventory(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, (tuple, list)) or len(raw) > MAX_ITEMS:
        raise ValueError("file_explorer_inventory_invalid")
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != FIELDS:
            raise ValueError("file_explorer_entry_invalid")
        source_id = _identifier(item["source_id"])
        parent_id = _identifier(item["parent_id"], nullable=True)
        name = item["name"]
        kind = item["kind"]
        revision = item["revision"]
        size = item["size_bytes"]
        checksum = item["sha256"]
        if source_id in ids or source_id == parent_id:
            raise ValueError("file_explorer_duplicate_or_self_parent")
        if not isinstance(name, str) or not 1 <= len(name) <= 256:
            raise ValueError("file_explorer_name_invalid")
        if kind not in {"file", "folder"}:
            raise ValueError("file_explorer_kind_invalid")
        if not isinstance(revision, str) or not 1 <= len(revision) <= 128:
            raise ValueError("file_explorer_revision_invalid")
        if type(size) is not int or not 0 <= size <= 10**15:
            raise ValueError("file_explorer_size_invalid")
        if checksum is not None and (
            kind != "file" or not isinstance(checksum, str) or not HEX64.fullmatch(checksum)
        ):
            raise ValueError("file_explorer_checksum_invalid")
        ids.add(source_id)
        result.append({
            "source_id": source_id, "parent_id": parent_id, "kind": kind,
            "name": name, "revision": revision, "size_bytes": size,
            "sha256": checksum,
        })
    return result


def execute(params: Mapping[str, Any], authorized_inventory: Any) -> dict[str, Any]:
    """Operate only on host-supplied entries; no client inventory is accepted."""
    if not isinstance(params, dict) or set(params) - {"operation", "parent_id", "source_ids"}:
        raise ValueError("file_explorer_parameters_invalid")
    operation = params.get("operation")
    if operation not in {"list", "select"}:
        raise ValueError("file_explorer_operation_invalid")
    entries = _inventory(authorized_inventory)
    by_id = {entry["source_id"]: entry for entry in entries}
    if operation == "list":
        if "source_ids" in params:
            raise ValueError("file_explorer_parameters_invalid")
        parent_id = _identifier(params.get("parent_id"), nullable=True)
        if parent_id is not None and (parent_id not in by_id or by_id[parent_id]["kind"] != "folder"):
            raise PermissionError("file_explorer_folder_not_in_authorized_snapshot")
        children = [entry.copy() for entry in entries if entry["parent_id"] == parent_id]
        children.sort(key=lambda entry: (entry["kind"] != "folder", entry["name"].casefold(), entry["source_id"]))
        return {"operation": "list", "parent_id": parent_id, "items": children,
                "inventory_semantics": "host_authorized_snapshot_not_live_acl",
                "persisted": False}
    if "parent_id" in params:
        raise ValueError("file_explorer_parameters_invalid")
    selected = params.get("source_ids")
    if (not isinstance(selected, list) or not 1 <= len(selected) <= MAX_SELECTION
            or len(selected) != len(set(str(value) for value in selected))):
        raise ValueError("file_explorer_selection_invalid")
    result = []
    for raw_id in selected:
        source_id = _identifier(raw_id)
        entry = by_id.get(source_id)
        if entry is None:
            raise PermissionError("file_explorer_source_not_in_authorized_snapshot")
        result.append({
            "source_id": source_id, "revision": entry["revision"],
            "kind": entry["kind"], "sha256": entry["sha256"],
        })
    return {"operation": "select", "selections": result,
            "source_ref_semantics": "reference_only_revalidate_at_consumer",
            "persisted": False}
