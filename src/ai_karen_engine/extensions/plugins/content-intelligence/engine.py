"""Bounded, deterministic and stateless text-content analysis for the plugin.

Inputs must have been authorized by the host. This module never opens files,
calls providers, writes durable memory or accesses a remote index.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any

TOKEN = re.compile(r"\b[\w]{3,}\b", re.UNICODE)
STOP = frozenset(
    "the and for with from that this have are was were has had not but you your "
    "their they them into our out all can will use used using then than about "
    "there here which would could should more some each when where what who "
    "how its those these also between been being document file project"
    .split()
)
MAX_DOCUMENTS = 12
MAX_TEXT_CHARS = 100_000
MAX_TOTAL_CHARS = 300_000
MAX_QUERY_CHARS = 512
MAX_RESULTS = 12


def _terms(value: str) -> list[str]:
    return [term for term in (token.casefold() for token in TOKEN.findall(value))
            if term not in STOP]


def _prepare(documents: Any) -> list[dict[str, Any]]:
    if not isinstance(documents, list) or not 1 <= len(documents) <= MAX_DOCUMENTS:
        raise ValueError("content_documents_count_invalid")
    checked: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    for document in documents:
        if not isinstance(document, dict) or set(document) != {"id", "name", "text"}:
            raise ValueError("content_document_shape_invalid")
        identifier, name, content = (document.get(key) for key in ("id", "name", "text"))
        if not isinstance(identifier, str) or not 1 <= len(identifier) <= 128 or identifier in seen:
            raise ValueError("content_document_id_invalid")
        if not isinstance(name, str) or not 1 <= len(name) <= 256:
            raise ValueError("content_document_name_invalid")
        if not isinstance(content, str) or not 1 <= len(content) <= MAX_TEXT_CHARS:
            raise ValueError("content_document_text_invalid")
        total += len(content)
        if total > MAX_TOTAL_CHARS:
            raise ValueError("content_document_budget_exceeded")
        seen.add(identifier)
        checked.append({"id": identifier, "name": name, "text": content})
    return checked


def _chunks(text: str) -> list[tuple[int, str]]:
    # Stable, bounded line-based evidence, preserving offsets into original text.
    chunks: list[tuple[int, str]] = []
    for match in re.finditer(r"[^\n]+", text):
        line = match.group().strip()
        if not line:
            continue
        chunks.append((match.start(), line[:600]))
    return chunks


def execute(params: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("content_input_invalid")
    allowed = {"operation", "documents", "query", "left_id", "right_id"}
    if set(params) - allowed:
        raise ValueError("content_unknown_parameter")
    operation = params.get("operation")
    if operation not in {"analyze", "search", "compare"}:
        raise ValueError("content_operation_invalid")
    documents = _prepare(params.get("documents"))
    counts = {doc["id"]: Counter(_terms(doc["text"])) for doc in documents}
    document_index = {doc["id"]: doc for doc in documents}
    common = []
    for left_index, left in enumerate(documents):
        for right in documents[left_index + 1:]:
            shared = set(counts[left["id"]]) & set(counts[right["id"]])
            if shared:
                common.append({
                    "left_id": left["id"], "right_id": right["id"],
                    "relationship": "shared_terms",
                    "terms": sorted(shared, key=lambda term: (-min(counts[left["id"]][term], counts[right["id"]][term]), term))[:10],
                })
    if operation == "analyze":
        return {
            "operation": operation,
            "documents": [{
                "id": doc["id"], "name": doc["name"],
                "sha256": hashlib.sha256(doc["text"].encode("utf-8")).hexdigest(),
                "characters": len(doc["text"]),
                "top_terms": [{"term": term, "count": count} for term, count in
                              sorted(counts[doc["id"]].items(), key=lambda pair: (-pair[1], pair[0]))[:12]]
            } for doc in documents],
            "relationships": common,
            "relationship_semantics": "lexical_hints_not_verified_entities",
            "persisted": False,
        }
    if operation == "compare":
        left_id, right_id = params.get("left_id"), params.get("right_id")
        if (not isinstance(left_id, str) or not isinstance(right_id, str)
                or left_id == right_id or left_id not in document_index
                or right_id not in document_index):
            raise ValueError("content_compare_selection_invalid")
        left_terms, right_terms = set(counts[left_id]), set(counts[right_id])
        intersection = left_terms & right_terms
        union = left_terms | right_terms
        return {
            "operation": operation, "left_id": left_id, "right_id": right_id,
            "shared_terms": sorted(intersection)[:100],
            "only_left": sorted(left_terms - right_terms)[:100],
            "only_right": sorted(right_terms - left_terms)[:100],
            "jaccard_similarity": round(len(intersection) / len(union), 4) if union else 1.0,
            "comparison_semantics": "lexical_not_semantic",
            "persisted": False,
        }
    query = params.get("query")
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= MAX_QUERY_CHARS:
        raise ValueError("content_query_invalid")
    terms = set(_terms(query))
    if not terms:
        raise ValueError("content_query_no_searchable_terms")
    hits: list[dict[str, Any]] = []
    for doc in documents:
        for offset, excerpt in _chunks(doc["text"]):
            matches = sorted(terms & set(_terms(excerpt)))
            if matches:
                hits.append({
                    "document_id": doc["id"], "document_name": doc["name"],
                    "offset": offset, "excerpt": excerpt, "matched_terms": matches,
                    "score": len(matches) / len(terms),
                })
    hits.sort(key=lambda hit: (-hit["score"], hit["document_id"], hit["offset"]))
    return {"operation": operation, "query": query, "matches": hits[:MAX_RESULTS],
            "search_semantics": "lexical_evidence_only", "persisted": False}
