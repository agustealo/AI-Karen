"""Provenance-only search graph contracts.

No mock graph store or inferred claims: inputs are the exact authorized
source/passages response shape that the canonical search service emits.
"""

from ai_karen_engine.services.search.evidence_graph_projection import (
    MAX_EVIDENCE_PASSAGES,
    MAX_EVIDENCE_SOURCES,
    project_search_evidence_graph,
)


def _source(url: str, level: str = "fetched_page") -> dict:
    return {
        "id": "source_0",
        "url": url,
        "title": "Source",
        "evidence_level": level,
    }


def _passage(url: str, content: str = "Verified excerpt") -> dict:
    return {
        "id": "chunk_0",
        "url": url,
        "title": "Passage",
        "content": content,
    }


def test_graph_only_links_passages_to_exact_fetched_source():
    url = "https://example.org/article"
    response = project_search_evidence_graph([_source(url)], [_passage(url)])
    assert response["status"] == "available"
    assert len(response["nodes"]) == 2
    assert len(response["edges"]) == 1
    edge = response["edges"][0]
    assert edge["type"] == "DERIVED_FROM"
    assert edge["verification_state"] == "source_matched"
    assert edge["provenance_url"] == url
    assert edge["from"] != edge["to"]


def test_discovery_only_result_never_claims_fetched_page_provenance():
    url = "https://example.org/discovery"
    response = project_search_evidence_graph(
        [_source(url, "search_snippet")], [_passage(url)]
    )
    assert [node["kind"] for node in response["nodes"]] == ["source"]
    assert response["nodes"][0]["evidence_level"] == "search_snippet"
    assert response["edges"] == []


def test_mismatched_url_cannot_be_related_to_source():
    response = project_search_evidence_graph(
        [_source("https://example.org/a")],
        [_passage("https://example.org/b")],
    )
    assert response["edges"] == []
    assert len(response["nodes"]) == 1


def test_empty_or_invalid_urls_never_create_nodes_or_edges():
    response = project_search_evidence_graph(
        [
            _source("file:///etc/passwd"),
            _source("https://user:pass@example.org/private"),
        ],
        [_passage("file:///etc/passwd")],
    )
    assert response["status"] == "empty"
    assert response["nodes"] == []
    assert response["edges"] == []


def test_stable_ids_dedup_and_bounded_response():
    url = "https://example.org/a"
    duplicate = project_search_evidence_graph(
        [_source(url), _source(url)], [_passage(url), _passage(url)]
    )
    once = project_search_evidence_graph([_source(url)], [_passage(url)])
    assert duplicate["nodes"] == once["nodes"]
    assert duplicate["edges"] == once["edges"]

    sources = [
        _source(f"https://example.org/{i}")
        for i in range(MAX_EVIDENCE_SOURCES + 5)
    ]
    passages = [
        _passage("https://example.org/0", str(i))
        for i in range(MAX_EVIDENCE_PASSAGES + 5)
    ]
    bounded = project_search_evidence_graph(sources, passages)
    assert bounded["truncated"] is True
    assert len(bounded["nodes"]) <= MAX_EVIDENCE_SOURCES + MAX_EVIDENCE_PASSAGES
    assert len(bounded["edges"]) <= MAX_EVIDENCE_PASSAGES


def test_no_claim_or_entity_relationship_inferred_from_text():
    url = "https://example.org/article"
    response = project_search_evidence_graph(
        [_source(url)],
        [_passage(url, "Organization A acquired Organization B")],
    )
    assert {node["kind"] for node in response["nodes"]} == {"source", "passage"}
    assert {edge["type"] for edge in response["edges"]} == {"DERIVED_FROM"}
