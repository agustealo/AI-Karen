"""Pure document operation and source-selection contract shared by policy and hosts.

No plugin discovery, execution, persistence, or authorization is performed here.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

MAX_CONTENT_SOURCE_REFERENCES = 12


def is_canonical_source_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except (TypeError, ValueError, AttributeError):
        return False


def _sha(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def validate_source_operation(
    operation: str, references: list[dict[str, str]], *,
    query: str | None, left_id: str | None, right_id: str | None,
) -> list[tuple[str, str]]:
    """Validate operation shape and pin selection before any await."""
    if operation not in {"analyze", "search", "compare"}:
        raise ValueError("content_source_operation_invalid")
    if not isinstance(references, list) or not 1 <= len(references) <= MAX_CONTENT_SOURCE_REFERENCES:
        raise ValueError("content_source_count_invalid")
    ids: set[str] = set()
    selection: list[tuple[str, str]] = []
    for ref in references:
        if (
            not isinstance(ref, dict)
            or set(ref) != {"source_id", "revision"}
            or not is_canonical_source_uuid(ref["source_id"])
            or not _sha(ref["revision"])
            or ref["source_id"] in ids
        ):
            raise PermissionError("content_source_reference_invalid")
        ids.add(ref["source_id"])
        selection.append((ref["source_id"], ref["revision"]))
    if operation == "search":
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 512:
            raise ValueError("content_source_query_invalid")
    elif query is not None:
        raise ValueError("content_source_unused_query")
    if operation == "compare":
        if left_id not in ids or right_id not in ids or left_id == right_id:
            raise ValueError("content_source_comparison_invalid")
    elif left_id is not None or right_id is not None:
        raise ValueError("content_source_unused_selection")
    return selection


def runtime_content_operation_digest(
    references: list[dict[str, str]], operation: Any,
) -> str:
    """Bind a validated operation and its arguments without publishing private query text."""
    if not isinstance(operation, dict):
        raise ValueError("content_source_operation_invalid")
    name = operation.get("operation")
    if not isinstance(name, str):
        raise ValueError("content_source_operation_invalid")
    fields = {"operation"}
    if name == "search":
        fields.add("query")
    elif name == "compare":
        fields.update({"left_id", "right_id"})
    if set(operation) != fields:
        raise ValueError("content_source_operation_invalid")
    validate_source_operation(
        name, references, query=operation.get("query"),
        left_id=operation.get("left_id"), right_id=operation.get("right_id"),
    )
    encoded = json.dumps(
        {"references": references, "operation": operation},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


