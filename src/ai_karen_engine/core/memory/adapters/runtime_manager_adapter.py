"""
Memory Runtime Manager Adapter for AI-Karen

Adapter that wraps the existing MemoryRuntimeManager to conform
to the new port interfaces, allowing gradual migration.

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ai_karen_engine.core.memory.protocols import ConsolidationPort, RetrievalPort
from ai_karen_engine.core.memory.types import MemoryEntry


class MemoryRuntimeManagerAdapter(RetrievalPort, ConsolidationPort):
    """
    Adapter that wraps the existing MemoryRuntimeManager to conform
    to the new port interfaces.
    """

    def __init__(self, memory_runtime_manager):
        self._manager = memory_runtime_manager

    def retrieve(self, query: str, *, top_k: int = 10, **filters) -> List[MemoryEntry]:
        """Retrieve memories matching a query."""
        try:
            results = self._manager.recall_context(query, limit=top_k, **filters)
            return [r for r in results if isinstance(r, MemoryEntry)]
        except Exception:
            return []

    def retrieve_by_id(self, entry_id: str) -> Optional[MemoryEntry]:
        """Retrieve a specific memory by ID."""
        try:
            return self._manager.get_memory(entry_id)
        except Exception:
            return None

    def retrieve_batch(self, entry_ids: List[str]) -> List[MemoryEntry]:
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
            return self._manager.get_consolidation_candidates(**criteria)
        except Exception:
            return []

    async def consolidate(self, entry: MemoryEntry) -> MemoryEntry:
        """Consolidate a memory."""
        try:
            return self._manager.consolidate_memory(entry)
        except Exception:
            return entry

    async def consolidate_batch(self, entries: List[MemoryEntry]) -> List[MemoryEntry]:
        """Consolidate multiple memories."""
        results = []
        for entry in entries:
            result = await self.consolidate(entry)
            results.append(result)
        return results
