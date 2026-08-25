"""
Unified Memory Protocols for AI-Karen

This module provides protocol (interface) definitions that consolidate:
- StoreAdapter (from recalls)
- VectorStore (from reasoning/retrieval)
- EmbeddingClient (from recalls)
- Storage protocols (from neuro_vault)

All memory system implementations should use these unified protocols.

Author: AI-Karen Core Team
Version: 1.0.0 (Unified Architecture)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple, runtime_checkable

from ai_karen_engine.core.memory.types import (
    EmbeddingVector,
    MemoryEntry,
    MemoryQuery,
    MemoryQueryResult,
)


# ===================================
# STORAGE PROTOCOLS
# ===================================

@runtime_checkable
class StorageBackend(Protocol):
    """
    Unified storage backend protocol.

    Consolidates:
    - StoreAdapter from recalls
    - VectorStore from reasoning/retrieval
    - Storage backends from neuro_vault

    Any storage system (Milvus, FAISS, pgvector, DuckDB, etc.)
    should implement this protocol.
    """

    def store(self, entry: MemoryEntry) -> str:
        """
        Store a single memory entry.

        Args:
            entry: Memory entry to store

        Returns:
            The ID of the stored entry

        Raises:
            StorageError: If storage fails
        """
        ...

    def store_batch(self, entries: Sequence[MemoryEntry]) -> List[str]:
        """
        Store multiple memory entries.

        Args:
            entries: Sequence of memory entries

        Returns:
            List of IDs of stored entries

        Raises:
            StorageError: If storage fails
        """
        ...

    def retrieve(self, entry_id: str) -> Optional[MemoryEntry]:
        """
        Retrieve a memory entry by ID.

        Args:
            entry_id: Memory ID

        Returns:
            MemoryEntry if found, None otherwise
        """
        ...

    def retrieve_batch(self, entry_ids: Sequence[str]) -> List[MemoryEntry]:
        """
        Retrieve multiple memory entries by ID.

        Args:
            entry_ids: Sequence of memory IDs

        Returns:
            List of found memory entries (may be shorter than input if some not found)
        """
        ...

    def search_vector(
        self,
        vector: EmbeddingVector,
        *,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Tuple[MemoryEntry, float]]:
        """
        Search by vector similarity.

        Args:
            vector: Query embedding vector
            top_k: Number of results to return
            filters: Optional filters (metadata, type, etc.)

        Returns:
            List of (MemoryEntry, distance/score) tuples,
            sorted by relevance (lower distance = more relevant for distance metrics)
        """
        ...

    def search_text(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Tuple[MemoryEntry, float]]:
        """
        Search by text query (requires text search capability).

        Args:
            query: Text query
            top_k: Number of results
            filters: Optional filters

        Returns:
            List of (MemoryEntry, relevance_score) tuples
        """
        ...

    def delete(self, entry_id: str) -> bool:
        """
        Delete a memory entry.

        Args:
            entry_id: Memory ID to delete

        Returns:
            True if deleted, False if not found
        """
        ...

    def delete_batch(self, entry_ids: Sequence[str]) -> int:
        """
        Delete multiple memory entries.

        Args:
            entry_ids: Memory IDs to delete

        Returns:
            Number of entries deleted
        """
        ...

    def update(self, entry: MemoryEntry) -> bool:
        """
        Update an existing memory entry.

        Args:
            entry: Updated memory entry (must have existing ID)

        Returns:
            True if updated, False if not found
        """
        ...

    def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """
        Count memories matching filters.

        Args:
            filters: Optional filters

        Returns:
            Count of matching memories
        """
        ...

    def list_ids(
        self,
        *,
        limit: Optional[int] = None,
        offset: int = 0,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        List memory IDs.

        Args:
            limit: Max number to return (None = all)
            offset: Pagination offset
            filters: Optional filters

        Returns:
            List of memory IDs
        """
        ...


# ===================================
# EMBEDDING PROTOCOLS
# ===================================

@runtime_checkable
class EmbeddingProvider(Protocol):
    """
    Unified embedding generation protocol.

    Consolidates:
    - EmbeddingClient from recalls
    - EmbeddingManager from neuro_vault
    - Embedding functionality from reasoning

    Any embedding service (HuggingFace, OpenAI, local model, etc.)
    should implement this protocol.
    """

    def embed_text(self, text: str, *, model: Optional[str] = None) -> EmbeddingVector:
        """
        Generate embedding for a single text.

        Args:
            text: Input text
            model: Optional model name/identifier

        Returns:
            Embedding vector

        Raises:
            EmbeddingError: If embedding generation fails
        """
        ...

    def embed_batch(
        self,
        texts: Sequence[str],
        *,
        model: Optional[str] = None
    ) -> List[EmbeddingVector]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: Sequence of input texts
            model: Optional model name/identifier

        Returns:
            List of embedding vectors (same order as input)

        Raises:
            EmbeddingError: If embedding generation fails
        """
        ...

    def embed_query(self, query: str, *, model: Optional[str] = None) -> EmbeddingVector:
        """
        Generate embedding for a query (may use different strategy than documents).

        Args:
            query: Query text
            model: Optional model name/identifier

        Returns:
            Query embedding vector

        Raises:
            EmbeddingError: If embedding generation fails
        """
        ...

    @property
    def dimension(self) -> int:
        """Get the embedding dimension for this provider."""
        ...

    @property
    def max_length(self) -> int:
        """Get the maximum text length supported."""
        ...


# ===================================
# RE-RANKING PROTOCOL
# ===================================

@runtime_checkable
class Reranker(Protocol):
    """
    Re-ranking protocol for improving search quality.

    Consolidates reranker interfaces from recalls and other systems.

    Re-rankers take initial retrieval results and reorder them
    using more sophisticated scoring (e.g., cross-encoders).
    """

    def rerank(
        self,
        query: str,
        candidates: Sequence[MemoryEntry],
        *,
        top_k: Optional[int] = None
    ) -> List[Tuple[MemoryEntry, float]]:
        """
        Re-rank candidate memories for a query.

        Args:
            query: Original query text
            candidates: Initial retrieval candidates
            top_k: Optional limit on results (None = rerank all)

        Returns:
            List of (MemoryEntry, reranked_score) tuples,
            sorted by score (higher = more relevant)
        """
        ...


# ===================================
# QUERY EXECUTION PROTOCOL
# ===================================

@runtime_checkable
class QueryExecutor(Protocol):
    """
    Protocol for executing memory queries with various strategies.

    Unifies query execution across all memory systems.
    """

    def execute(self, query: MemoryQuery) -> MemoryQueryResult:
        """
        Execute a memory query.

        Args:
            query: Memory query specification

        Returns:
            Query results with metadata

        Raises:
            QueryError: If query execution fails
        """
        ...

    async def execute_async(self, query: MemoryQuery) -> MemoryQueryResult:
        """
        Execute a memory query asynchronously.

        Args:
            query: Memory query specification

        Returns:
            Query results with metadata

        Raises:
            QueryError: If query execution fails
        """
        ...


# ===================================
# CONSOLIDATION PROTOCOL
# ===================================

@runtime_checkable
class MemoryConsolidator(Protocol):
    """
    Protocol for memory consolidation (e.g., episodic → semantic).

    Based on HippoRAG hippocampal consolidation model.
    """

    def identify_candidates(self, **criteria) -> List[MemoryEntry]:
        """
        Identify memories eligible for consolidation.

        Args:
            **criteria: Consolidation criteria (access count, importance, age, etc.)

        Returns:
            List of candidate memories
        """
        ...

    async def consolidate(self, entry: MemoryEntry) -> MemoryEntry:
        """
        Consolidate a memory (e.g., episodic → semantic).

        Args:
            entry: Memory to consolidate

        Returns:
            Consolidated memory entry

        Raises:
            ConsolidationError: If consolidation fails
        """
        ...

    async def consolidate_batch(self, entries: Sequence[MemoryEntry]) -> List[MemoryEntry]:
        """
        Consolidate multiple memories.

        Args:
            entries: Memories to consolidate

        Returns:
            List of consolidated memories

        Raises:
            ConsolidationError: If consolidation fails
        """
        ...


# ===================================
# MEMORY MANAGER PROTOCOL
# ===================================

@runtime_checkable
class MemoryManager(Protocol):
    """
    High-level memory manager protocol.

    Provides unified interface for all memory operations.
    This is the main interface that applications should use.
    """

    # === Storage Operations ===

    def store(self, entry: MemoryEntry) -> str:
        """Store a memory."""
        ...

    def retrieve(self, entry_id: str) -> Optional[MemoryEntry]:
        """Retrieve a memory by ID."""
        ...

    def delete(self, entry_id: str) -> bool:
        """Delete a memory."""
        ...

    # === Query Operations ===

    def query(self, query: MemoryQuery) -> MemoryQueryResult:
        """Execute a memory query."""
        ...

    async def query_async(self, query: MemoryQuery) -> MemoryQueryResult:
        """Execute a memory query asynchronously."""
        ...

    # === Convenience Methods ===

    def recall(
        self,
        query_text: str,
        *,
        top_k: int = 10,
        **filters
    ) -> List[MemoryEntry]:
        """
        Quick recall by text query.

        Args:
            query_text: Query text
            top_k: Number of results
            **filters: Additional filters

        Returns:
            List of relevant memories
        """
        ...

    def store_text(
        self,
        content: str,
        *,
        memory_type: str = "episodic",
        importance: float = 5.0,
        **metadata
    ) -> str:
        """
        Quick store of text content.

        Args:
            content: Text to store
            memory_type: Type of memory
            importance: Importance score
            **metadata: Additional metadata

        Returns:
            Memory ID
        """
        ...


# ===================================
# RECALL PORT
# ===================================

@runtime_checkable
class RecallPort(Protocol):
    """
    Port for memory recall operations.

    This is the interface that reasoning, cortex, and other core modules
    use to retrieve memories. Implementations live in runtime/ or platform/.
    """

    def query(self, query_text: str, *, top_k: int = 10, **filters) -> List[MemoryEntry]:
        """Query memories by text."""
        ...

    def decompose(self, query: str) -> List[str]:
        """Decompose a query into sub-queries for multi-hop retrieval."""
        ...

    def fuse(self, results: List[List[MemoryEntry]]) -> List[MemoryEntry]:
        """Fuse multiple retrieval result lists."""
        ...

    def rerank(self, query: str, candidates: Sequence[MemoryEntry], *, top_k: Optional[int] = None) -> List[Tuple[MemoryEntry, float]]:
        """Re-rank candidates for a query."""
        ...


# ===================================
# RETRIEVAL PORT
# ===================================

@runtime_checkable
class RetrievalPort(Protocol):
    """
    Port for memory retrieval operations.

    Implementations live in platform/ (postgres, redis, milvus, etc.).
    """

    def retrieve(self, query: str, *, top_k: int = 10, **filters) -> List[MemoryEntry]:
        """Retrieve memories matching a query."""
        ...

    def retrieve_by_id(self, entry_id: str) -> Optional[MemoryEntry]:
        """Retrieve a specific memory by ID."""
        ...

    def retrieve_batch(self, entry_ids: Sequence[str]) -> List[MemoryEntry]:
        """Retrieve multiple memories by ID."""
        ...


# ===================================
# CONSOLIDATION PORT
# ===================================

@runtime_checkable
class ConsolidationPort(Protocol):
    """
    Port for memory consolidation operations.

    Implementations live in platform/.
    """

    def identify_candidates(self, **criteria) -> List[MemoryEntry]:
        """Identify memories eligible for consolidation."""
        ...

    def consolidate(self, entry: MemoryEntry) -> MemoryEntry:
        """Consolidate a memory (e.g., episodic → semantic)."""
        ...

    def consolidate_batch(self, entries: Sequence[MemoryEntry]) -> List[MemoryEntry]:
        """Consolidate multiple memories."""
        ...


# ===================================
# EMBEDDING PORT
# ===================================

@runtime_checkable
class EmbeddingPort(Protocol):
    """
    Port for embedding operations.

    Implementations live in runtime/ or providers/.
    Core must not instantiate EmbeddingManager directly.
    """

    def embed_text(self, text: str, *, model: Optional[str] = None) -> EmbeddingVector:
        """Generate embedding for a single text."""
        ...

    def embed_batch(self, texts: Sequence[str], *, model: Optional[str] = None) -> List[EmbeddingVector]:
        """Generate embeddings for multiple texts."""
        ...

    def embed_query(self, query: str, *, model: Optional[str] = None) -> EmbeddingVector:
        """Generate embedding for a query."""
        ...


# ===================================
# HELPER TYPE ALIASES
# ===================================

# Storage result (ID, success flag, optional error)
StorageResult = Tuple[str, bool, Optional[str]]

# Search result (Memory, score)
SearchResult = Tuple[MemoryEntry, float]


# ===================================
# EXPORTS
# ===================================

__all__ = [
    # Core protocols
    "StorageBackend",
    "EmbeddingProvider",
    "Reranker",
    "QueryExecutor",
    "MemoryConsolidator",
    "MemoryManager",
    # CORE-SPLIT-2 ports
    "RecallPort",
    "RetrievalPort",
    "ConsolidationPort",
    "EmbeddingPort",
    # Type aliases
    "StorageResult",
    "SearchResult",
]
