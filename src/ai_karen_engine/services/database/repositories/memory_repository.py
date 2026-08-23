"""Memory repository contract for KAREN's durable memory layer."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import Repository, RepositoryResult


@dataclass
class MemoryItem:
    """Canonical memory item representation."""

    id: str
    tenant_id: str
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None
    memory_type: str = "episodic"
    content: str = ""
    content_tsv: Optional[str] = None
    embedding: Optional[List[float]] = None
    embedding_model: str = "unknown"
    embedding_version: str = "v1"
    embedding_dimension: int = 0
    embedded_at: datetime = field(default_factory=datetime.utcnow)
    importance: float = 0.5
    confidence: float = 1.0
    source_type: str = "system"
    source_ref: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "memory_type": self.memory_type,
            "content": self.content,
            "content_tsv": self.content_tsv,
            "embedding": self.embedding,
            "embedding_model": self.embedding_model,
            "embedding_version": self.embedding_version,
            "embedding_dimension": self.embedding_dimension,
            "embedded_at": self.embedded_at.isoformat() if self.embedded_at else None,
            "importance": self.importance,
            "confidence": self.confidence,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "metadata": self.metadata,
        }


@dataclass
class MemoryQuery:
    """Query parameters for memory retrieval."""

    tenant_id: str
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None
    memory_type: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    scope: Optional[str] = None
    time_range: Optional[tuple[datetime, datetime]] = None
    top_k: int = 10
    similarity_threshold: float = 0.7
    include_embeddings: bool = False


@dataclass
class HybridSearchResult:
    """Result from hybrid semantic + lexical search."""

    item: MemoryItem
    semantic_score: float = 0.0
    lexical_score: float = 0.0
    combined_score: float = 0.0
    signals: Dict[str, float] = field(default_factory=dict)


class MemoryRepository(Repository):
    """Canonical contract for durable memory persistence.

    Implementations must NOT expose backend-specific types (pgvector,
    Milvus, Elasticsearch, etc.).  The domain layer sees only MemoryItem
    and MemoryQuery.
    """

    @abstractmethod
    async def store_memory(self, item: MemoryItem) -> RepositoryResult[str]:
        """Persist a memory item. Returns the assigned id."""

    @abstractmethod
    async def update_memory(self, item: MemoryItem) -> RepositoryResult[bool]:
        """Update an existing memory item by id."""

    @abstractmethod
    async def delete_memory(self, memory_id: str, tenant_id: str) -> RepositoryResult[bool]:
        """Soft or hard delete a memory item."""

    @abstractmethod
    async def get_memory(self, memory_id: str, tenant_id: str) -> RepositoryResult[Optional[MemoryItem]]:
        """Retrieve a single memory item by id."""

    @abstractmethod
    async def list_by_scope(self, query: MemoryQuery) -> RepositoryResult[List[MemoryItem]]:
        """List memory items filtered by scope, type, time range, etc."""

    @abstractmethod
    async def search_semantic(
        self, query: MemoryQuery, embedding: List[float]
    ) -> RepositoryResult[List[HybridSearchResult]]:
        """Vector similarity search over memory embeddings."""

    @abstractmethod
    async def search_keyword(self, query: MemoryQuery) -> RepositoryResult[List[HybridSearchResult]]:
        """Lexical full-text search over memory content."""

    @abstractmethod
    async def search_hybrid(
        self, query: MemoryQuery, embedding: List[float]
    ) -> RepositoryResult[List[HybridSearchResult]]:
        """Combined semantic + lexical search. Returns ranked candidates."""

    @abstractmethod
    async def count(self, tenant_id: str, user_id: Optional[str] = None) -> RepositoryResult[int]:
        """Count memory items for a tenant / user."""
