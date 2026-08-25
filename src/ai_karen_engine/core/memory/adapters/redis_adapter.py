"""
Redis Memory Adapter for AI-Karen

Adapter that wraps existing Redis memory implementations
to conform to the new port interfaces.

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from collections.abc import Sequence

from ai_karen_engine.core.memory.protocols import RetrievalPort
from ai_karen_engine.core.memory.types import MemoryEntry


class RedisMemoryAdapter(RetrievalPort):
    """
    Adapter that wraps existing Redis memory implementations
    to conform to the RetrievalPort interface.
    """

    def __init__(self, redis_client, redis_connection_manager):
        self._redis_client = redis_client
        self._redis_connection_manager = redis_connection_manager

    def retrieve(self, query: str, *, top_k: int = 10, **filters) -> list[MemoryEntry]:
        """Retrieve memories matching a query from Redis."""
        try:
            results = self._redis_connection_manager.search_memories(
                query, limit=top_k, **filters
            )
            return [r for r in results if isinstance(r, MemoryEntry)]
        except Exception:
            return []

    def retrieve_by_id(self, entry_id: str) -> MemoryEntry | None:
        """Retrieve a specific memory by ID from Redis."""
        try:
            return self._redis_connection_manager.get_memory(entry_id)
        except Exception:
            return None

    def retrieve_batch(self, entry_ids: Sequence[str]) -> list[MemoryEntry]:
        """Retrieve multiple memories by ID from Redis."""
        results = []
        for entry_id in entry_ids:
            entry = self.retrieve_by_id(entry_id)
            if entry is not None:
                results.append(entry)
        return results
