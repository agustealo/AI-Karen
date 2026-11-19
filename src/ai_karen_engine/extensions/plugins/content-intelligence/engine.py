"""Bounded, deterministic, stateless content analysis for authorized invocation data.

This plugin engine does not read files, access memory, select models, query
external indexes, or grant access based on document/folder metadata.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any

TOKEN = re.compile(r"\b[\w]{3,}\b", re.UNICODE)
LINES = re.compile(r"[^\n]+")
FOLDER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
STOP = frozenset(
    "the and for with from that this have are was were has had not but you your "
    "their they them into our out all can will use used using then than about "
    "there here which would could should more some each when where what who "
    "how its those these also between been being document file project".split()
)
MAX_DOCUMENTS = 12
MAX_TEXT_CHARS = 100_000
MAX_TOTAL_CHARS = 300_000
MAX_QUERY_CHARS = 512
MAX_RESULTS = 12
MAX_EXCERPT_CHARS = 600
MAX_RELATED_TERMS = 10
DOCUMENT_FIELDS = frozenset({"id", "name", "text", "folder_id"})
OPERATIONS = frozenset({"analyze", "search", "compare"})


def _terms(value: str) -> list[str]:
    return [
        term
        for term in (token.casefold() for token in TOKEN.findall(value))
        if term not in STOP
    ]


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _prepare(documents: Any) -> list[dict[str, Any]]:
    if not isinstance(documents, list) or not 1 <= len(documents) <= MAX_DOCUMENTS:
        raise ValueError("content_documents_count_invalid")
    checked: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    for document in documents:
        if (
            not isinstance(document, dict)
            or not {"id", "name", "text"} <= set(document)
            or set(document) - DOCUMENT_FIELDS
        ):
            raise ValueError("content_document_shape_invalid")
        identifier = document["id"]
        name = document["name"]
        content = document["text"]
        folder_id = document.get("folder_id")
        if (
            not isinstance(identifier, str)
            or not 1 <= len(identifier) <= 128
            or identifier in seen
        ):
            raise ValueError("content_document_id_invalid")
        if not isinstance(name, str) or not 1 <= len(name) <= 256:
            raise ValueError("content_document_name_invalid")
        if not isinstance(content, str) or not 1 <= len(content) <= MAX_TEXT_CHARS:
            raise ValueError("content_document_text_invalid")
        if (
            folder_id is not None
            and (
                not isinstance(folder_id, str)
                or FOLDER_ID.fullmatch(folder_id) is None
                or folder_id in {".", ".."}
            )
        ):
            raise ValueError("content_folder_label_invalid")
        total += len(content)
        if total > MAX_TOTAL_CHARS:
            raise ValueError("content_document_budget_exceeded")
        seen.add(identifier)
        checked.append({
            "id": identifier,
            "name": name,
            "text": content,
            "folder_id": folder_id,
            "sha256": _checksum(content),
        })
    return checked


def _chunks(text: str) -> list[tuple[int, int, str]]:
    """Return exact spans, including all nonempty content on long lines."""
    result: list[tuple[int, int, str]] = []
    for line in LINES.finditer(text):
        start, stop = line.span()
        for offset in range(start, stop, MAX_EXCERPT_CHARS):
            end = min(offset + MAX_EXCERPT_CHARS, stop)
            fragment = text[offset:end]
            if fragment.strip():
                result.append((offset, end, fragment))
    return result


def _relationships(
    documents: list[dict[str, Any]], counts: dict[str, Counter[str]]
) -> list[dict[str, Any]]:
    related: list[dict[str, Any]] = []
    for position, left in enumerate(documents):
        for right in documents[position + 1:]:
            overlap = set(counts[left["id"]]) & set(counts[right["id"]])
            if overlap:
                related.append({
                    "left_id": left["id"],
                    "right_id": right["id"],
                    "relationship": "shared_terms",
                    "terms": sorted(
                        overlap,
                        key=lambda term: (
                            -min(counts[left["id"]][term], counts[right["id"]][term]),
                            term,
                        ),
                    )[:MAX_RELATED_TERMS],
                })
    return related


def execute(params: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("content_input_invalid")
    allowed = {"operation", "documents", "query", "left_id", "right_id"}
    if set(params) - allowed:
        raise ValueError("content_unknown_parameter")
    operation = params.get("operation")
    if operation not in OPERATIONS:
        raise ValueError("content_operation_invalid")
    documents = _prepare(params.get("documents"))
    counts = {doc["id"]: Counter(_terms(doc["text"])) for doc in documents}
    document_index = {doc["id"]: doc for doc in documents}

    if operation == "analyze":
        if set(params) - {"operation", "documents"}:
            raise ValueError("content_analyze_parameters_invalid")
        return {
            "operation": operation,
            "documents": [{
                "id": doc["id"],
                "name": doc["name"],
                "folder_id": doc["folder_id"],
                "sha256": doc["sha256"],
                "characters": len(doc["text"]),
                "top_terms": [
                    {"term": term, "count": count}
                    for term, count in sorted(
                        counts[doc["id"]].items(),
                        key=lambda pair: (-pair[1], pair[0]),
                    )[:12]
                ],
            } for doc in documents],
            "relationships": _relationships(documents, counts),
            "relationship_semantics": "lexical_hints_not_verified_entities",
            "persisted": False,
        }

    if operation == "compare":
        if set(params) - {"operation", "documents", "left_id", "right_id"}:
            raise ValueError("content_compare_parameters_invalid")
        left_id, right_id = params.get("left_id"), params.get("right_id")
        if (
            not isinstance(left_id, str)
            or not isinstance(right_id, str)
            or left_id == right_id
            or left_id not in document_index
            or right_id not in document_index
        ):
            raise ValueError("content_compare_selection_invalid")
        left_terms, right_terms = set(counts[left_id]), set(counts[right_id])
        intersection = left_terms & right_terms
        union = left_terms | right_terms
        return {
            "operation": operation,
            "left_id": left_id,
            "right_id": right_id,
            "left_sha256": document_index[left_id]["sha256"],
            "right_sha256": document_index[right_id]["sha256"],
            "shared_terms": sorted(intersection)[:100],
            "only_left": sorted(left_terms - right_terms)[:100],
            "only_right": sorted(right_terms - left_terms)[:100],
            "jaccard_similarity": (
                round(len(intersection) / len(union), 4) if union else 1.0
            ),
            "comparison_semantics": "lexical_not_semantic",
            "persisted": False,
        }

    if set(params) - {"operation", "documents", "query"}:
        raise ValueError("content_search_parameters_invalid")
    query = params.get("query")
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= MAX_QUERY_CHARS:
        raise ValueError("content_query_invalid")
    terms = set(_terms(query))
    if not terms:
        raise ValueError("content_query_no_searchable_terms")

    hits: list[dict[str, Any]] = []
    for doc in documents:
        for start, end, excerpt in _chunks(doc["text"]):
            matches = sorted(terms & set(_terms(excerpt)))
            if matches:
                hits.append({
                    "document_id": doc["id"],
                    "document_name": doc["name"],
                    "folder_id": doc["folder_id"],
                    "sha256": doc["sha256"],
                    "offset": start,
                    "end_offset": end,
                    "excerpt": excerpt,
                    "matched_terms": matches,
                    "score": len(matches) / len(terms),
                })
    hits.sort(key=lambda hit: (-hit["score"], hit["document_id"], hit["offset"]))
    return {
        "operation": operation,
        "query": query,
        "matches": hits[:MAX_RESULTS],
        "search_semantics": "lexical_evidence_only",
        "persisted": False,
    }
