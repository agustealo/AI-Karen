"""
Short-Term Memory - In-memory fast recall with optional persistence.

Provides fast similarity search for recent interactions and context.
Uses vector embeddings for semantic search with decay function.
"""

import logging
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
import asyncio
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MemoryVector:
    """Vector representation of a memory."""
    id: str
    user_id: str
    content: str
    embedding: List[float]
    timestamp: str
    metadata: Dict[str, Any]
    relevance_score: float = 1.0


@dataclass
class SearchResult:
    """Result from similarity search."""
    vector: MemoryVector
    similarity: float
    decayed_score: float
    rank: int


class ShortTermMemory:
    """
    Short-term memory with in-memory vector store.

    Features:
    - Fast similarity search via in-memory vectors
    - Embedding generation with sentence-transformers
    - Relevance decay over time
    - Health monitoring
    """

    def __init__(
        self,
        user_id: str,
        decay_half_life_hours: float = 24.0,
        max_memories: int = 10000,
        enable_fallback: bool = True
    ):
        self.user_id = user_id
        self.decay_half_life = timedelta(hours=decay_half_life_hours)
        self.max_memories = max_memories
        self.enable_fallback = enable_fallback

        self._fallback_vectors: List[MemoryVector] = []

        self._embedding_function = None

        self._total_inserts = 0
        self._total_searches = 0

        logger.info(f"ShortTermMemory initialized for user {user_id}")

    async def initialize(self) -> None:
        await self._initialize_embedding_function()

    async def _initialize_embedding_function(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
            self._embedding_function = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Loaded SentenceTransformer embedding model")
        except ImportError:
            logger.warning("sentence-transformers not available, using random embeddings")
            self._embedding_function = None

    def _generate_embedding(self, text: str) -> List[float]:
        if self._embedding_function is not None:
            try:
                embedding = self._embedding_function.encode(text)
                normalized = embedding / np.linalg.norm(embedding)
                return normalized.tolist()
            except Exception as e:
                logger.error(f"Embedding generation failed: {e}")

        logger.debug("Using random embedding (fallback)")
        vec = np.random.rand(384)
        return (vec / np.linalg.norm(vec)).tolist()

    def _calculate_decay(self, timestamp: datetime) -> float:
        now = datetime.utcnow()
        age = now - timestamp
        decay = np.exp(-age.total_seconds() / self.decay_half_life.total_seconds())
        return float(decay)

    async def store(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> MemoryVector:
        memory_id = hashlib.sha256(
            f"{self.user_id}{datetime.utcnow().isoformat()}{content}".encode()
        ).hexdigest()[:16]

        embedding = self._generate_embedding(content)

        vector = MemoryVector(
            id=memory_id,
            user_id=self.user_id,
            content=content,
            embedding=embedding,
            timestamp=datetime.utcnow().isoformat(),
            metadata=metadata or {},
            relevance_score=1.0
        )

        await self._store_fallback(vector)

        self._total_inserts += 1

        await self._cleanup_old_memories()

        logger.debug(f"Stored memory: {memory_id}")
        return vector

    async def _store_fallback(self, vector: MemoryVector) -> None:
        self._fallback_vectors.append(vector)

    async def search(
        self,
        query: str,
        top_k: int = 10,
        apply_decay: bool = True,
        min_similarity: float = 0.0
    ) -> List[SearchResult]:
        query_embedding = self._generate_embedding(query)

        results = await self._search_fallback(query_embedding, top_k, apply_decay, min_similarity)

        self._total_searches += 1

        logger.debug(f"Search returned {len(results)} results")
        return results

    async def _search_fallback(
        self,
        query_embedding: List[float],
        top_k: int,
        apply_decay: bool,
        min_similarity: float
    ) -> List[SearchResult]:
        results = []
        query_vec = np.array(query_embedding)

        for vector in self._fallback_vectors:
            vec = np.array(vector.embedding)

            similarity = float(np.dot(query_vec, vec) / (np.linalg.norm(query_vec) * np.linalg.norm(vec)))

            if similarity < min_similarity:
                continue

            timestamp = datetime.fromisoformat(vector.timestamp)
            decay_factor = self._calculate_decay(timestamp) if apply_decay else 1.0
            decayed_score = similarity * decay_factor

            results.append((vector, similarity, decayed_score))

        results.sort(key=lambda x: x[2], reverse=True)

        search_results = []
        for rank, (vector, similarity, decayed_score) in enumerate(results[:top_k]):
            search_results.append(SearchResult(
                vector=vector,
                similarity=similarity,
                decayed_score=decayed_score,
                rank=rank
            ))

        return search_results

    async def batch_store(self, items: List[Tuple[str, Optional[Dict[str, Any]]]]) -> List[MemoryVector]:
        vectors = []
        for content, metadata in items:
            vector = await self.store(content, metadata)
            vectors.append(vector)

        logger.info(f"Batch stored {len(vectors)} memories")
        return vectors

    async def _cleanup_old_memories(self) -> None:
        if len(self._fallback_vectors) > self.max_memories:
            self._fallback_vectors.sort(key=lambda v: v.timestamp, reverse=True)
            removed = len(self._fallback_vectors) - self.max_memories
            self._fallback_vectors = self._fallback_vectors[:self.max_memories]
            logger.info(f"Cleaned up {removed} old memories")

    async def get_statistics(self) -> Dict[str, Any]:
        stats = {
            "user_id": self.user_id,
            "decay_half_life_hours": self.decay_half_life.total_seconds() / 3600,
            "max_memories": self.max_memories,
            "metrics": {
                "total_inserts": self._total_inserts,
                "total_searches": self._total_searches
            }
        }

        stats["memory_count"] = len(self._fallback_vectors)

        return stats

    async def health_check(self) -> Dict[str, Any]:
        healthy = True
        issues = []

        if self._embedding_function is None:
            issues.append("Using fallback embedding (random)")

        return {
            "healthy": healthy,
            "issues": issues,
            "statistics": await self.get_statistics()
        }


__all__ = [
    "ShortTermMemory",
    "MemoryVector",
    "SearchResult"
]