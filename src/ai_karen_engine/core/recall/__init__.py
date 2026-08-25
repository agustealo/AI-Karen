"""
Recall Authority for AI-Karen

Unified recall authority that consolidates:
- core/memory/retrieval/recall_manager.py (RecallManager)
- core/memory/retrieval/retrieval_router.py (HybridRetrievalRouter)
- core/memory/neuro/ (activation, scoring, decay)
- core/reasoning/retrieval/ (reasoning-specific retrieval)

This module owns retrieval strategy, query decomposition, fusion, reranking,
spreading activation, and associative recall.

Memory storage remains in core/memory/ and platform/.

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ai_karen_engine.core.memory.contracts import RecallScoreComponents
from ai_karen_engine.core.memory.protocols import RecallPort, RetrievalPort
from ai_karen_engine.core.memory.types import MemoryEntry


# ===================================
# RECALL IMPLEMENTATIONS
# ===================================

class DefaultRecallService(RecallPort):
    """
    Default recall service that wraps existing retrieval implementations
    and presents a unified RecallPort interface.
    """

    def __init__(
        self,
        retrieval_port: Optional[RetrievalPort] = None,
        recall_manager: Optional[Any] = None,
        retrieval_router: Optional[Any] = None,
    ):
        self._retrieval_port = retrieval_port
        self._recall_manager = recall_manager
        self._retrieval_router = retrieval_router

    def set_retrieval_port(self, port: RetrievalPort) -> None:
        """Set the retrieval port implementation."""
        self._retrieval_port = port

    def set_recall_manager(self, manager: Any) -> None:
        """Set the legacy recall manager."""
        self._recall_manager = manager

    def set_retrieval_router(self, router: Any) -> None:
        """Set the legacy retrieval router."""
        self._retrieval_router = router

    def query(self, query_text: str, *, top_k: int = 10, **filters) -> List[MemoryEntry]:
        """Query memories by text using the best available backend."""
        # Prefer the new retrieval port if available
        if self._retrieval_port is not None:
            try:
                return self._retrieval_port.retrieve(query_text, top_k=top_k, **filters)
            except Exception:
                pass

        # Fall back to legacy recall manager
        if self._recall_manager is not None:
            try:
                from ai_karen_engine.core.memory.retrieval.recall_manager import RecallQuery
                query = RecallQuery(task=query_text, top_k=top_k)
                results = self._recall_manager.retrieve_recalls(query)
                return [r for r in results if isinstance(r, MemoryEntry)]
            except Exception:
                pass

        # Fall back to retrieval router
        if self._retrieval_router is not None:
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
                pass

        return []

    def decompose(self, query: str) -> List[str]:
        """Decompose a query into sub-queries for multi-hop retrieval."""
        # Simple decomposition: return the query as-is
        # Can be extended with LLM-based decomposition
        return [query]

    def fuse(self, results: List[List[MemoryEntry]]) -> List[MemoryEntry]:
        """Fuse multiple retrieval result lists using reciprocal rank fusion."""
        try:
            from ai_karen_engine.core.memory.retrieval.fusion import reciprocal_rank_fusion
            return reciprocal_rank_fusion(results)
        except Exception:
            # Fallback: simple deduplication
            fused = []
            seen = set()
            for result_list in results:
                for entry in result_list:
                    if entry.id not in seen:
                        fused.append(entry)
                        seen.add(entry.id)
            return fused

    def rerank(self, query: str, candidates: Sequence[MemoryEntry], *, top_k: Optional[int] = None) -> List[Tuple[MemoryEntry, float]]:
        """Re-rank candidates for a query."""
        try:
            from ai_karen_engine.core.memory.retrieval.rerank import rerank_entries
            return rerank_entries(query, list(candidates), top_k=top_k)
        except Exception:
            # Fallback: return candidates with uniform score
            return [(c, 1.0) for c in candidates]
