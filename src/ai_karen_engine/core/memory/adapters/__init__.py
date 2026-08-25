"""
Memory Adapters for AI-Karen

Adapters bridge existing memory implementations to the new port interfaces.
This allows gradual migration without breaking existing functionality.

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Dict, List, Optional, Tuple

from ai_karen_engine.core.memory.protocols import (
    ConsolidationPort,
    EmbeddingPort,
    RecallPort,
    RetrievalPort,
)
from ai_karen_engine.core.memory.types import MemoryEntry


class LegacyEmbeddingManagerAdapter(EmbeddingPort):
    """Adapter for legacy EmbeddingManager to EmbeddingPort."""

    def __init__(self, embedding_manager):
        self._embedding_manager = embedding_manager

    def embed_text(self, text: str, *, model: str | None = None) -> list[float]:
        """Generate embedding for a single text."""
        if hasattr(self._embedding_manager, "embed_text"):
            return self._embedding_manager.embed_text(text, model=model)
        if hasattr(self._embedding_manager, "generate_embedding"):
            return self._embedding_manager.generate_embedding(text)
        raise NotImplementedError("EmbeddingManager does not support embed_text")

    def embed_batch(self, texts: Sequence[str], *, model: str | None = None) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        if hasattr(self._embedding_manager, "embed_batch"):
            return self._embedding_manager.embed_batch(texts, model=model)
        return [self.embed_text(text, model=model) for text in texts]

    def embed_query(self, query: str, *, model: str | None = None) -> list[float]:
        """Generate embedding for a query."""
        if hasattr(self._embedding_manager, "embed_query"):
            return self._embedding_manager.embed_query(query, model=model)
        return self.embed_text(query, model=model)


class LegacyMemoryServiceAdapter(RetrievalPort):
    """Adapter for legacy memory service to RetrievalPort."""

    def __init__(self, memory_service):
        self._memory_service = memory_service

    def retrieve(self, query: str, *, top_k: int = 10, **filters) -> list[MemoryEntry]:
        """Retrieve memories matching a query."""
        if hasattr(self._memory_service, "query_memories"):
            results = self._memory_service.query_memories(query, limit=top_k, **filters)
            return [r for r in results if isinstance(r, MemoryEntry)]
        return []

    def retrieve_by_id(self, entry_id: str) -> MemoryEntry | None:
        """Retrieve a specific memory by ID."""
        if hasattr(self._memory_service, "get_memory"):
            result = self._memory_service.get_memory(entry_id)
            return result if isinstance(result, MemoryEntry) else None
        return None

    def retrieve_batch(self, entry_ids: Sequence[str]) -> list[MemoryEntry]:
        """Retrieve multiple memories by ID."""
        results = []
        for entry_id in entry_ids:
            entry = self.retrieve_by_id(entry_id)
            if entry is not None:
                results.append(entry)
        return results


class LegacyRecallManagerAdapter(RecallPort):
    """Adapter for legacy RecallManager to RecallPort."""

    def __init__(self, recall_manager):
        self._recall_manager = recall_manager

    def query(self, query_text: str, *, top_k: int = 10, **filters) -> list[MemoryEntry]:
        """Query memories by text."""
        if hasattr(self._recall_manager, "retrieve_recalls"):
            from ai_karen_engine.core.memory.retrieval.recall_manager import RecallQuery
            query = RecallQuery(task=query_text, top_k=top_k)
            results = self._recall_manager.retrieve_recalls(query)
            return [r for r in results if isinstance(r, MemoryEntry)]
        return []

    def decompose(self, query: str) -> list[str]:
        """Decompose a query into sub-queries."""
        return [query]

    def fuse(self, results: list[list[MemoryEntry]]) -> list[MemoryEntry]:
        """Fuse multiple retrieval result lists."""
        fused = []
        seen = set()
        for result_list in results:
            for entry in result_list:
                if entry.id not in seen:
                    fused.append(entry)
                    seen.add(entry.id)
        return fused

    def rerank(self, query: str, candidates: Sequence[MemoryEntry], *, top_k: int | None = None) -> list[tuple[MemoryEntry, float]]:
        """Re-rank candidates for a query."""
        if hasattr(self._recall_manager, "rerank"):
            return self._recall_manager.rerank(query, candidates, top_k=top_k)
        return [(c, 1.0) for c in candidates]
