"""Retired Neo4j graph cannot bypass the canonical memory authorization path."""

from __future__ import annotations

import importlib
from pathlib import Path

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


def test_no_repository_python_runtime_directly_consumes_legacy_client() -> None:
    """Audit active Python source imports/references, not only filenames."""
    root = Path(__file__).resolve().parents[2]
    excluded = {
        root / "src/ai_karen_engine/services/knowledge/knowledge_graph_client.py",
        root / "src/ai_karen_engine/services/knowledge/__init__.py",
        Path(__file__).resolve(),
    }
    references: list[str] = []
    for dirname in ("src", "server", "scripts", "plugins", "free_plugins"):
        base = root / dirname
        if not base.is_dir():
            continue
        for source in base.rglob("*.py"):
            if source in excluded:
                continue
            content = source.read_text(encoding="utf-8")
            if "KnowledgeGraphClient" in content or "knowledge_graph_client" in content:
                references.append(source.relative_to(root).as_posix())

    assert not references, (
        "Unexpected direct Neo4j compatibility consumers must migrate to "
        f"canonical runtime authorization: {sorted(references)}"
    )
