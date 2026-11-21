"""Retired Neo4j graph cannot bypass the canonical memory authorization path."""

from __future__ import annotations

import importlib

import pytest


def test_knowledge_package_retains_import_without_neo4j_dependency() -> None:
    package = importlib.import_module("ai_karen_engine.services.knowledge")
    legacy = importlib.import_module(
        "ai_karen_engine.services.knowledge.knowledge_graph_client"
    )
    assert package.KnowledgeGraphClient is legacy.KnowledgeGraphClient
    assert issubclass(legacy.KnowledgeGraphUnavailableError, legacy.KnowledgeGraphError)
    assert issubclass(legacy.ConnectionError, legacy.KnowledgeGraphError)
    assert issubclass(legacy.QueryExecutionError, legacy.KnowledgeGraphError)


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"uri": "bolt://localhost:7687"},
        {"uri": "bolt://remote.example:7687", "user": "legacy", "password": "secret"},
        {"max_retries": 1, "connection_timeout": 1},
    ],
)
def test_legacy_client_fails_before_connection_even_with_explicit_credentials(
    arguments: dict[str, object],
) -> None:
    from ai_karen_engine.services.knowledge.knowledge_graph_client import (
        KnowledgeGraphClient,
        KnowledgeGraphUnavailableError,
    )

    with pytest.raises(KnowledgeGraphUnavailableError) as failure:
        KnowledgeGraphClient(**arguments)

    assert "canonical PostgreSQL memory graph" in str(failure.value)
    assert "secret" not in str(failure.value)
    assert "remote.example" not in str(failure.value)


def test_legacy_raw_query_and_destructive_methods_are_not_available() -> None:
    from ai_karen_engine.services.knowledge.knowledge_graph_client import (
        KnowledgeGraphClient,
    )

    for method in (
        "execute_cypher", "find_related_concepts", "get_concept_graph",
        "upsert_node", "batch_upsert_nodes", "delete_node",
        "upsert_relationship", "delete_relationship", "clear_all",
    ):
        assert method not in KnowledgeGraphClient.__dict__
