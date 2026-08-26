"""PostgreSQL platform adapters for the memory domain.

Concrete database behavior lives here. Core memory owns contracts and recall
strategy; this package only implements PostgreSQL-specific persistence access.
"""

from .recall_retriever import PostgresRecallRetriever, PostgresRecallScopeError

__all__ = ["PostgresRecallRetriever", "PostgresRecallScopeError"]
