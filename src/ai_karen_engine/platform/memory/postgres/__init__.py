"""PostgreSQL platform adapters for the memory domain.

Concrete database behavior lives here. Core memory owns contracts, governance
semantics, and recall strategy; this package only implements PostgreSQL-specific
persistence and retrieval access.
"""

from .graph_repository import PostgresGraphRepository, PostgresGraphScopeError
from .recall_retriever import PostgresRecallRetriever, PostgresRecallScopeError
from .vault import (
    NeuroVaultAuthorizationError,
    NeuroVaultScopeError,
    PostgresNeuroVault,
)

__all__ = [
    "NeuroVaultAuthorizationError",
    "NeuroVaultScopeError",
    "PostgresGraphRepository",
    "PostgresGraphScopeError",
    "PostgresNeuroVault",
    "PostgresRecallRetriever",
    "PostgresRecallScopeError",
]
