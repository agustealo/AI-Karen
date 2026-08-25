"""
Postgres Memory Adapter for AI-Karen

Adapter that bridges existing Postgres memory code to the new RetrievalPort
and ConsolidationPort interfaces. This allows gradual migration without
breaking existing functionality.

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ai_karen_engine.core.memory.protocols import ConsolidationPort, RetrievalPort
from ai_karen_engine.core.memory.types import MemoryEntry, MemoryQuery


class PostgresMemoryAdapter(RetrievalPort, ConsolidationPort):
    """
    Adapter that wraps existing Postgres memory implementations
    to conform to the new port interfaces.
    """

    def __init__(self, db_client, memory_manager):
        self._db_client = db_client
        self._memory_manager = memory_manager

    def retrieve(self, query: str, *, top_k: int = 10, **filters) -> List[MemoryEntry]:
        """Retrieve memories matching a query."""
        try:
            results = self._memory_manager.query_memories(
                query_text=query,
                limit=top_k,
                **filters
            )
            return [r for r in results if isinstance(r, MemoryEntry)]
        except Exception:
            return []

    def retrieve_by_id(self, entry_id: str) -> Optional[MemoryEntry]:
        """Retrieve a specific memory by ID."""
        try:
            return self._memory_manager.get_memory(entry_id)
        except Exception:
            return None

    def retrieve_batch(self, entry_ids: Sequence[str]) -> List[MemoryEntry]:
        """Retrieve multiple memories by ID."""
        results = []
        for entry_id in entry_ids:
            entry = self.retrieve_by_id(entry_id)
            if entry is not None:
                results.append(entry)
        return results

    def identify_candidates(self, **criteria) -> List[MemoryEntry]:
        """Identify memories eligible for consolidation."""
        try:
            return self._memory_manager.get_consolidation_candidates(**criteria)
        except Exception:
            return []

    async def consolidate(self, entry: MemoryEntry) -> MemoryEntry:
        """Consolidate a memory."""
        try:
            return self._memory_manager.consolidate_memory(entry)
        except Exception:
            return entry

    async def consolidate_batch(self, entries: Sequence[MemoryEntry]) -> List[MemoryEntry]:
        """Consolidate multiple memories."""
        results = []
        for entry in entries:
            result = await self.consolidate(entry)
            results.append(result)
        return results
