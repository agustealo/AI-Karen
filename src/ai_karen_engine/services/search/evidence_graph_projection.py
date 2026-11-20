"""Read-only evidence relationship projection for authorized search responses.

This is not the durable memory graph or an entity/claim extraction engine.
It exposes only exact URL provenance between source records and passages
already selected by InternetCapabilityService. Never invent semantic edges.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

MAX_EVIDENCE_SOURCES = 10
MAX_EVIDENCE_PASSAGES = 12


def _url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if len(candidate) > 2048:
        return None
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    return candidate


def _id(kind: str, key: str) -> str:
    return f"{kind}_{hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]}"


def project_search_evidence_graph(
    sources: Sequence[Mapping[str, Any]],
    passages: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Make a bounded evidence-only graph from an already-authorized search result.

    The only edge type is DERIVED_FROM. It is emitted when a fetched-page
    passage has exactly the same source URL. Search-snippet-only links and
    unmatched passages never imply the underlying page was verified.
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    fetched_by_url: dict[str, str] = {}
    observed_urls: set[str] = set()

    for source in sources[:MAX_EVIDENCE_SOURCES]:
        url = _url(source.get("url"))
        if not url or url in observed_urls:
            continue
        observed_urls.add(url)
        level = (
            "fetched_page"
            if source.get("evidence_level") == "fetched_page"
            else "search_snippet"
        )
        node_id = _id("source", url)
        nodes.append(
            {
                "id": node_id,
                "kind": "source",
                "label": str(source.get("title") or url)[:180],
                "url": url,
                "evidence_level": level,
                "article_id": (
                    source.get("article_id")
                    if isinstance(source.get("article_id"), str)
                    else None
                ),
                "published_at": (
                    source.get("publishedDate")
                    if isinstance(source.get("publishedDate"), str)
                    else None
                ),
            }
        )
        if level == "fetched_page":
            fetched_by_url[url] = node_id

    seen_passage_ids: set[str] = set()
    for passage in passages[:MAX_EVIDENCE_PASSAGES]:
        url = _url(passage.get("url"))
        if not url or url not in fetched_by_url:
            continue
        raw_key = str(passage.get("id") or "")
        raw_content = str(passage.get("content") or passage.get("snippet") or "")
        passage_id = _id("passage", f"{url}\0{raw_key}\0{raw_content[:512]}")
        if passage_id in seen_passage_ids:
            continue
        seen_passage_ids.add(passage_id)
        nodes.append(
            {
                "id": passage_id,
                "kind": "passage",
                "label": str(passage.get("title") or "Retrieved passage")[:180],
                "url": url,
                "evidence_level": "fetched_page",
            }
        )
        source_id = fetched_by_url[url]
        edges.append(
            {
                "id": _id("edge", f"{passage_id}\0{source_id}"),
                "from": passage_id,
                "to": source_id,
                "type": "DERIVED_FROM",
                "provenance_url": url,
                "verification_state": "source_matched",
            }
        )

    return {
        "version": 1,
        "kind": "retrieval_evidence",
        "status": "available" if nodes else "empty",
        "nodes": nodes,
        "edges": edges,
        "truncated": (
            len(sources) > MAX_EVIDENCE_SOURCES
            or len(passages) > MAX_EVIDENCE_PASSAGES
        ),
    }
