"""
Recall Adapters for AI-Karen

Adapters bridge existing retrieval implementations to the new RecallPort interface.

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from ai_karen_engine.core.memory.protocols import RecallPort, RetrievalPort
from ai_karen_engine.core.memory.types import MemoryEntry


class RecallManagerRecallAdapter(RecallPort):
    """Adapts the legacy RecallManager to RecallPort."""

    def __init__(self, recall_manager: Any):
        self._recall_manager = recall_manager

    def query(self, query_text: str, *, top_k: int = 10, **filters) -> List[MemoryEntry]:
        """Query using legacy RecallManager."""
        try:
            from ai_karen_engine.core.memory.retrieval.recall_manager import RecallQuery
            query = RecallQuery(task=query_text, top_k=top_k)
            results = self._recall_manager.retrieve_recalls(query)
            return [r for r in results if isinstance(r, MemoryEntry)]
        except Exception:
            return []

    def decompose(self, query: str) -> List[str]:
        """Decompose query."""
        return [query]

    def fuse(self, results: List[List[MemoryEntry]]) -> List[MemoryEntry]:
        """Fuse results."""
        fused = []
        seen = set()
        for result_list in results:
            for entry in result_list:
                if entry.id not in seen:
                    fused.append(entry)
                    seen.add(entry.id)
        return fused

    def rerank(self, query: str, candidates: Sequence[MemoryEntry], *, top_k: Optional[int] = None) -> List[Tuple[MemoryEntry, float]]:
        """Re-rank candidates."""
        return [(c, 1.0) for c in candidates]


class RetrievalRouterRecallAdapter(RecallPort):
    """Adapts the legacy HybridRetrievalRouter to RecallPort."""

    def __init__(self, retrieval_router: Any):
        self._retrieval_router = retrieval_router

    def query(self, query_text: str, *, top_k: int = 10, **filters) -> List[MemoryEntry]:
        """Query using legacy HybridRetrievalRouter."""
        try:
            import asyncio
            from ai_karen_engine.core.memory.types import MemoryQuery
            mem_query = MemoryQuery(
                text=query_text,
                user_id=filters.get("user_id"),
                tenant_id=filters.get("tenant_id"),
                top_k=top_k,
            )
            return asyncio.run(self._retrieval_router.recall(mem_query))
        except Exception:
            return []

    def decompose(self, query: str) -> List[str]:
        """Decompose query."""
        return [query]

    def fuse(self, results: List[List[MemoryEntry]]) -> List[MemoryEntry]:
        """Fuse results."""
        fused = []
        seen = set()
        for result_list in results:
            for entry in result_list:
                if entry.id not in seen:
                    fused.append(entry)
                    seen.add(entry.id)
        return fused

    def rerank(self, query: str, candidates: Sequence[MemoryEntry], *, top_k: Optional[int] = None) -> List[Tuple[MemoryEntry, float]]:
        """Re-rank candidates."""
        return [(c, 1.0) for c in candidates]
