"""
Runtime Memory Coordinator for AI-Karen

Coordinates memory operations at runtime, delegating to platform implementations
via port interfaces. Core must not directly import platform-specific implementations.

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ai_karen_engine.core.memory.contracts import (
    CognitiveMemoryEntry,
    CognitiveMemoryType,
    MemoryClaim,
    ProspectiveMemory,
    RecallScoreComponents,
    SalienceScore,
)
from ai_karen_engine.core.memory.protocols import (
    ConsolidationPort,
    EmbeddingPort,
    RecallPort,
    RetrievalPort,
)


class RuntimeMemoryCoordinator:
    """
    Coordinates memory operations at runtime.

    This is the runtime-side memory authority. It delegates to platform
    implementations via port interfaces.
    """

    def __init__(
        self,
        retrieval_port: Optional[RetrievalPort] = None,
        consolidation_port: Optional[ConsolidationPort] = None,
        embedding_port: Optional[EmbeddingPort] = None,
        recall_port: Optional[RecallPort] = None,
    ):
        self._retrieval_port = retrieval_port
        self._consolidation_port = consolidation_port
        self._embedding_port = embedding_port
        self._recall_port = recall_port

    def set_retrieval_port(self, port: RetrievalPort) -> None:
        """Set the retrieval port implementation."""
        self._retrieval_port = port

    def set_consolidation_port(self, port: ConsolidationPort) -> None:
        """Set the consolidation port implementation."""
        self._consolidation_port = port

    def set_embedding_port(self, port: EmbeddingPort) -> None:
        """Set the embedding port implementation."""
        self._embedding_port = port

    def set_recall_port(self, port: RecallPort) -> None:
        """Set the recall port implementation."""
        self._recall_port = port

    async def store(self, entry: CognitiveMemoryEntry) -> str:
        """Store a cognitive memory entry."""
        if self._retrieval_port is None:
            raise RuntimeError("RetrievalPort not configured")
        # Convert CognitiveMemoryEntry to base MemoryEntry for storage
        base_entry = entry.base_entry
        return self._retrieval_port.retrieve_by_id(base_entry.id) or ""

    async def retrieve(self, memory_id: str) -> Optional[CognitiveMemoryEntry]:
        """Retrieve a cognitive memory entry by ID."""
        if self._retrieval_port is None:
            raise RuntimeError("RetrievalPort not configured")
        base_entry = self._retrieval_port.retrieve_by_id(memory_id)
        if base_entry is None:
            return None
        return CognitiveMemoryEntry(base_entry=base_entry)

    async def recall(self, query: str, *, top_k: int = 10) -> List[CognitiveMemoryEntry]:
        """Recall memories using the recall port."""
        if self._recall_port is None:
            raise RuntimeError("RecallPort not configured")
        results = self._recall_port.query(query, top_k=top_k)
        return [CognitiveMemoryEntry(base_entry=entry) for entry in results]

    async def embed(self, text: str, *, model: Optional[str] = None):
        """Generate embedding using the embedding port."""
        if self._embedding_port is None:
            raise RuntimeError("EmbeddingPort not configured")
        return self._embedding_port.embed_text(text, model=model)

    async def embed_batch(self, texts: Sequence[str], *, model: Optional[str] = None):
        """Generate embeddings for multiple texts."""
        if self._embedding_port is None:
            raise RuntimeError("EmbeddingPort not configured")
        return self._embedding_port.embed_batch(texts, model=model)

    async def consolidate(self, entry: CognitiveMemoryEntry) -> CognitiveMemoryEntry:
        """Consolidate a memory entry."""
        if self._consolidation_port is None:
            raise RuntimeError("ConsolidationPort not configured")
        consolidated = self._consolidation_port.consolidate(entry.base_entry)
        return CognitiveMemoryEntry(base_entry=consolidated)
