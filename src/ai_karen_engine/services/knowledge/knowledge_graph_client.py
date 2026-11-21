"""Retired compatibility import for the ungoverned Neo4j knowledge graph.

This is intentionally not a functional graph backend. The previous client
opened an independent Neo4j connection and exposed raw Cypher, unscopeable
traversals and graph mutations without tenant, user, provenance or RBAC proof.

Memory graph storage is owned by the canonical PostgreSQL GraphRepository;
only runtime-governed NeuroRecall results may enter memory-evidence displays.
Do not reintroduce an execution fallback or bypass via this compatibility API.
"""

from __future__ import annotations


class KnowledgeGraphError(RuntimeError):
    """Base error for the retired legacy knowledge graph interface."""


class ConnectionError(KnowledgeGraphError):
    """Retained historical exception name for import compatibility."""


class QueryExecutionError(KnowledgeGraphError):
    """Retained historical exception name for import compatibility."""


class KnowledgeGraphUnavailableError(KnowledgeGraphError):
    """The legacy Neo4j graph interface has no authorized runtime owner."""


class KnowledgeGraphClient:
    """Import-compatible, fail-closed replacement for the legacy Neo4j client.

    All construction, including explicit URI and credential requests, is
    denied before network, database, filesystem or graph side effects occur.
    Consumers must migrate to the canonical scoped memory runtime; this class
    never returns synthetic query results or claims degraded success.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise KnowledgeGraphUnavailableError(
            "Legacy Neo4j knowledge graph access is disabled: use the "
            "canonical PostgreSQL memory graph through authorized runtime recall"
        )


__all__ = [
    "KnowledgeGraphClient",
    "KnowledgeGraphError",
    "KnowledgeGraphUnavailableError",
    "ConnectionError",
    "QueryExecutionError",
]
