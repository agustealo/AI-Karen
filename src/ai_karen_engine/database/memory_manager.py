# -*- coding: utf-8 -*-
"""
Utilities for storing and querying memory entries.

Production-ready manager:
- Async SQLAlchemy for metadata
- Canonical MemoryRepository via PostgreSQL + pgvector + FTS
- Optional Redis cache
- Optional metrics hooks
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from sqlalchemy import select, text

from ai_karen_engine.core.model_runtime.embedding_manager import EmbeddingManager
from ai_karen_engine.database.models import TenantMemoryItem

try:
    from ai_karen_engine.monitoring.metrics_service import MetricsService
    get_metrics_service = MetricsService if MetricsService else None
except Exception:
    get_metrics_service = None

logger = logging.getLogger(__name__)


@dataclass
class MemoryItem:
    """Represents a memory item with all associated data."""

    id: str
    content: str
    embedding: Optional[np.ndarray] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    scope: Optional[str] = None
    kind: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    similarity_score: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "metadata": self.metadata,
            "scope": self.scope,
            "kind": self.kind,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "tags": self.tags,
            "timestamp": self.timestamp,
            "similarity_score": self.similarity_score,
        }


MemoryEntry = MemoryItem


@dataclass
class MemoryQuery:
    """Represents a memory query with all parameters."""

    text: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    scope: Optional[str] = None
    kind: Optional[str] = None
    metadata_filter: Dict[str, Any] = field(default_factory=dict)
    query_embedding: Optional[List[float]] = None
    time_range: Optional[Tuple[datetime, datetime]] = None
    top_k: int = 10
    similarity_threshold: float = 0.7
    include_embeddings: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text[:100] + "..." if len(self.text) > 100 else self.text,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "tags": self.tags,
            "scope": self.scope,
            "kind": self.kind,
            "metadata_filter": self.metadata_filter,
            "has_query_embedding": self.query_embedding is not None,
            "time_range": (
                [t.isoformat() for t in self.time_range] if self.time_range else None
            ),
            "top_k": self.top_k,
            "similarity_threshold": self.similarity_threshold,
        }


try:
    from ai_karen_engine.database.client import MultiTenantPostgresClient
except Exception:  # pragma: no cover
    MultiTenantPostgresClient = Any  # type: ignore[misc,assignment]


class MemoryManager:
    """Production-grade memory management system."""

    def __init__(
        self,
        db_client: MultiTenantPostgresClient,
        embedding_manager: EmbeddingManager,
        redis_client: Optional[Any] = None,
        memory_repository: Optional[Any] = None,
    ):
        self.db_client = db_client
        self.embedding_manager = embedding_manager
        self.redis_client = redis_client
        self.memory_repository = memory_repository

        self.default_ttl_hours = 24 * 7
        self.cache_ttl_seconds = int(os.getenv("KARI_MEMORY_CACHE_TTL", "300"))
        self.recency_alpha = float(os.getenv("KARI_MEMORY_RECENCY_ALPHA", "0.05"))

        self._metrics = (
            get_metrics_service() if callable(get_metrics_service or None) else None
        )

        self.metrics: Dict[str, Union[int, float]] = {
            "queries_total": 0,
            "queries_cached": 0,
            "embeddings_generated": 0,
            "memories_stored": 0,
            "memories_retrieved": 0,
            "avg_query_time": 0.0,
            "avg_embedding_time": 0.0,
        }

    async def store_memory(
        self,
        tenant_id: Union[str, uuid.UUID],
        content: str,
        scope: str,
        kind: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        start_time = time.time()

        try:
            await self._ensure_embedding_manager()
            emb_t0 = time.time()
            embedding_raw = await self.embedding_manager.get_embedding(content)
            embedding = (
                np.array(embedding_raw)
                if not isinstance(embedding_raw, np.ndarray)
                else embedding_raw
            )
            emb_dt = time.time() - emb_t0

            memory_id = str(uuid.uuid4())

            if self.memory_repository is not None:
                from ai_karen_engine.services.database.repositories import MemoryItem as RepoMemoryItem
                item = RepoMemoryItem(
                    id=memory_id,
                    tenant_id=str(tenant_id),
                    content=content,
                    embedding=embedding.tolist(),
                    memory_type=kind or scope,
                    metadata=metadata or {},
                )
                result = await self.memory_repository.store_memory(item)
                if not result.success:
                    logger.warning("Canonical memory store failed: %s", result.error)
                    return None
                self.metrics["memories_stored"] = int(self.metrics["memories_stored"]) + 1
                self.metrics["embeddings_generated"] = int(self.metrics["embeddings_generated"]) + 1
                self.metrics["avg_embedding_time"] = self._roll(
                    float(self.metrics["avg_embedding_time"]), emb_dt
                )
                total_dt = time.time() - start_time
                logger.info(
                    f"Stored memory {memory_id} for tenant={tenant_id} in {total_dt:.3f}s (canonical)"
                )
                return memory_id

            logger.warning("MemoryRepository unavailable; cannot store memory")
            return None

        except Exception as e:
            logger.error(f"Failed to store memory for tenant {tenant_id}: {e}")
            if self._metrics:
                try:
                    self._metrics.record_memory_commit(
                        status="error", decay_tier="", user_id="", org_id=""
                    )
                except Exception as metrics_err:
                    logger.warning(f"Failed to record memory commit error metrics: {metrics_err}")
            raise

    async def query_memories(
        self, tenant_id: Union[str, uuid.UUID], query: MemoryQuery
    ) -> List[MemoryEntry]:
        t0 = time.time()
        self.metrics["queries_total"] = int(self.metrics["queries_total"]) + 1

        try:
            if self.memory_repository is not None:
                await self._ensure_embedding_manager()
                q_emb_raw = await self.embedding_manager.get_embedding(query.text)
                q_emb = (
                    np.array(q_emb_raw)
                    if not isinstance(q_emb_raw, np.ndarray)
                    else q_emb_raw
                )
                from ai_karen_engine.services.database.repositories import MemoryQuery as CanonicalMemoryQuery
                canonical_query = CanonicalMemoryQuery(
                    tenant_id=str(tenant_id),
                    user_id=query.user_id,
                    conversation_id=query.conversation_id,
                    memory_type=query.kind,
                    top_k=query.top_k,
                    similarity_threshold=query.similarity_threshold,
                    include_embeddings=query.include_embeddings,
                )
                result = await self.memory_repository.search_hybrid(canonical_query, q_emb.tolist())
                if not result.success:
                    logger.warning("Canonical memory query failed: %s", result.error)
                    return []
                memories = []
                for hybrid_result in result.data:
                    entry = MemoryEntry(
                        id=hybrid_result.item.id,
                        content=hybrid_result.item.content,
                        embedding=np.array(hybrid_result.item.embedding) if hybrid_result.item.embedding else None,
                        metadata=hybrid_result.item.metadata,
                        scope=hybrid_result.item.memory_type,
                        kind=hybrid_result.item.memory_type,
                        similarity_score=hybrid_result.combined_score,
                    )
                    memories.append(entry)
                self.metrics["memories_retrieved"] = int(self.metrics["memories_retrieved"]) + len(memories)
                dt = time.time() - t0
                self.metrics["avg_query_time"] = self._roll(
                    float(self.metrics["avg_query_time"]), dt
                )
                return memories

            logger.warning("MemoryRepository unavailable; cannot query memories")
            return []

        except Exception as e:
            logger.error(f"Failed to query memories for tenant {tenant_id}: {e}")
            raise

    async def delete_memory(
        self, tenant_id: Union[str, uuid.UUID], memory_id: str
    ) -> bool:
        try:
            if self.memory_repository is not None:
                result = await self.memory_repository.delete_memory(memory_id, str(tenant_id))
                return result.success and bool(result.data)

            logger.warning("MemoryRepository unavailable; cannot delete memory")
            return False

        except Exception as e:
            logger.error(
                f"Failed to delete memory {memory_id} for tenant {tenant_id}: {e}"
            )
            return False

    async def prune_expired_memories(self, tenant_id: Union[str, uuid.UUID]) -> int:
        logger.info(
            "prune_expired_memories called – not applicable for memory_items table"
        )
        return 0

    async def _ensure_embedding_manager(self) -> None:
        if getattr(self, "embedding_manager", None) is not None:
            return
        try:
            from ai_karen_engine.core.model_runtime import default_models
            try:
                await default_models.load_default_models()
            except Exception:
                pass
            self.embedding_manager = default_models.get_embedding_manager()
            return
        except Exception:
            try:
                local_manager = EmbeddingManager()
                try:
                    await local_manager.initialize()
                except Exception:
                    pass
                self.embedding_manager = local_manager
            except Exception as e:
                logger.error(f"Failed to provision embedding manager fallback: {e}")
                self.embedding_manager = None

    async def get_memory_stats(
        self, tenant_id: Union[str, uuid.UUID]
    ) -> Dict[str, Any]:
        try:
            async with self.db_client.get_async_session() as session:
                total_res = await session.execute(select(TenantMemoryItem.id))
                total_count = len(total_res.fetchall())

                recent_cutoff = datetime.utcnow() - timedelta(hours=24)
                recent_res = await session.execute(
                    select(TenantMemoryItem.id).where(
                        TenantMemoryItem.created_at > recent_cutoff
                    )
                )
                recent_count = len(recent_res.fetchall())

                schema = self.db_client.get_tenant_schema_name(tenant_id)
                scope_counts: Dict[Tuple[str, str], int] = {}
                try:
                    scope_sql = text(
                        f"""
                        SELECT scope, kind, COUNT(*) AS count
                        FROM {schema}.memory_items
                        GROUP BY scope, kind
                        """
                    )
                    scope_res = await session.execute(scope_sql)
                    for row in scope_res.fetchall():
                        scope_counts[(row[0], row[1])] = int(row[2])
                except Exception as e:
                    logger.debug(f"Scope/kind stats query failed (non-fatal): {e}")

            return {
                "total_memories": total_count,
                "recent_memories_24h": recent_count,
                "memories_by_scope_kind": scope_counts,
                "metrics": dict(self.metrics),
            }

        except Exception as e:
            logger.error(f"Failed to get memory stats for tenant {tenant_id}: {e}")
            return {"error": str(e)}

    @staticmethod
    def _roll(current: float, x: float, alpha: float = 0.1) -> float:
        return current * (1 - alpha) + x * alpha

    async def _get_cached_query(self, cache_key: str) -> Optional[List[MemoryEntry]]:
        if not self.redis_client:
            return None
        try:
            raw = await self.redis_client.get(cache_key)
            if not raw:
                return None
            data = json.loads(raw)
            items: List[MemoryEntry] = [MemoryEntry(**d) for d in data]
            return items
        except Exception as e:
            logger.debug(f"Cache read failed (non-fatal): {e}")
            return None

    async def _cache_query_result(
        self, cache_key: str, memories: List[MemoryEntry]
    ) -> None:
        if not self.redis_client:
            return
        try:
            payload = json.dumps([m.to_dict() for m in memories])
            await self.redis_client.setex(cache_key, self.cache_ttl_seconds, payload)
        except Exception as e:
            logger.debug(f"Cache write failed (non-fatal): {e}")

    async def _cache_memory(
        self, tenant_id: Union[str, uuid.UUID], memory: MemoryEntry
    ) -> None:
        if not self.redis_client:
            return
        try:
            key = f"memory:{tenant_id}:{memory.id}"
            await self.redis_client.setex(
                key, self.cache_ttl_seconds, json.dumps(memory.to_dict())
            )
        except Exception as e:
            logger.debug(f"Cache write (single) failed (non-fatal): {e}")

    async def _clear_memory_cache(
        self, tenant_id: Union[str, uuid.UUID], memory_id: str
    ) -> None:
        if not self.redis_client:
            return
        try:
            key = f"memory:{tenant_id}:{memory_id}"
            await self.redis_client.delete(key)
        except Exception as e:
            logger.debug(f"Cache delete failed (non-fatal): {e}")

    def _get_cache_key(
        self, tenant_id: Union[str, uuid.UUID], query: MemoryQuery
    ) -> str:
        q = json.dumps(query.to_dict(), sort_keys=True, default=str)
        h = hashlib.md5(q.encode("utf-8")).hexdigest()
        return f"memory_query:{tenant_id}:{h}"


__all__ = [
    "MemoryManager",
    "MemoryItem",
    "MemoryEntry",
    "MemoryQuery",
]