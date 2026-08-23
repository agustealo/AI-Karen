# -*- coding: utf-8 -*-
"""
Utilities for storing and querying memory entries.

Production-ready manager:
- Async SQLAlchemy for metadata
- Optional Milvus for vector search (graceful fallback)
- Optional Redis cache
- Optional Elasticsearch full-text indexing
- Optional metrics hooks (ai_karen_engine.services.metrics_service)
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
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from sqlalchemy import delete, select, text

from ai_karen_engine.core.model_runtime.embedding_manager import EmbeddingManager  # Required
from ai_karen_engine.core.model_runtime.milvus_client import MilvusClient  # Optional at runtime
from ai_karen_engine.database.models import TenantMemoryItem

# Optional metrics
try:
    from ai_karen_engine.monitoring.metrics_service import MetricsService
    get_metrics_service = MetricsService if MetricsService else None
except Exception:  # pragma: no cover
    get_metrics_service = None  # type: ignore[assignment]

logger: logging.Logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


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


# Backwards compatibility alias
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


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


if TYPE_CHECKING:
    from ai_karen_engine.database.client import MultiTenantPostgresClient
else:  # pragma: no cover - used only for type checking to avoid circular imports
    MultiTenantPostgresClient = Any  # type: ignore[misc,assignment]


class MemoryManager:
    """
    Production-grade memory management system.

    Constructor order matters (non-default args first) to avoid SyntaxError.
    """

    def __init__(
        self,
        db_client: MultiTenantPostgresClient,
        embedding_manager: EmbeddingManager,
        milvus_client: Optional[MilvusClient] = None,
        redis_client: Optional[Any] = None,
        elasticsearch_client: Optional[Any] = None,
        memory_repository: Optional[Any] = None,
    ):
        """
        Args:
            db_client: Database client for metadata (async sessions)
            embedding_manager: Embedding generation manager (async)
            milvus_client: Vector DB client (optional, deprecated)
            redis_client: Redis for cache (optional, must be awaitable API)
            elasticsearch_client: Elasticsearch client (optional, deprecated)
            memory_repository: Canonical MemoryRepository (preferred)
        """
        self.db_client = db_client
        self.embedding_manager = embedding_manager
        self.milvus_client = milvus_client
        self.redis_client = redis_client
        self.elasticsearch_client = elasticsearch_client
        self.memory_repository = memory_repository

        # Configuration
        self.default_ttl_hours = 24 * 7  # 1 week (retention handled externally)
        self.cache_ttl_seconds = int(os.getenv("KARI_MEMORY_CACHE_TTL", "300"))
        self.surprise_threshold = float(
            os.getenv("KARI_MEMORY_SURPRISE_THRESHOLD", "0.85")
        )
        self.disable_surprise_check = (
            os.getenv("KARI_DISABLE_MEMORY_SURPRISE_FILTER", "false").lower() == "true"
        )
        self.recency_alpha = float(os.getenv("KARI_MEMORY_RECENCY_ALPHA", "0.05"))
        self.milvus_metric_mode = os.getenv(
            "KARI_MILVUS_METRIC_MODE", "similarity"
        ).lower()
        # valid modes: "similarity" (higher=more similar) | "distance" (lower=more similar)

        # Fallback vector search scan limit (for Postgres-only / no Milvus)
        self.fallback_scan_limit = int(
            os.getenv("KARI_MEMORY_FALLBACK_SCAN_LIMIT", "500")
        )
        self.fallback_similarity_threshold = float(
            os.getenv("KARI_MEMORY_FALLBACK_SIMILARITY_THRESHOLD", "0.35")
        )

        # Metrics
        self._metrics = (
            get_metrics_service() if callable(get_metrics_service or None) else None
        )

        # Perf counters (simple rolling stats)
        self.metrics: Dict[str, Union[int, float]] = {
            "queries_total": 0,
            "queries_cached": 0,
            "embeddings_generated": 0,
            "memories_stored": 0,
            "memories_retrieved": 0,
            "avg_query_time": 0.0,
            "avg_embedding_time": 0.0,
        }

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def store_memory(
        self,
        tenant_id: Union[str, uuid.UUID],
        content: str,
        scope: str,
        kind: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Store a memory item with vector embedding.
        Returns the memory ID or None if dedup/surprise filter declines storage.
        """
        start_time = time.time()

        try:
            # Ensure we have an embedding manager available
            await self._ensure_embedding_manager()
            # Generate embedding
            emb_t0 = time.time()
            embedding_raw = await self.embedding_manager.get_embedding(content)
            embedding = (
                np.array(embedding_raw)
                if not isinstance(embedding_raw, np.ndarray)
                else embedding_raw
            )
            emb_dt = time.time() - emb_t0

            # Surprise / dedup check (vector similar content)
            is_surprising = await self._check_surprise(
                tenant_id, embedding, scope, kind
            )
            if not is_surprising:
                logger.debug("Content not surprising enough; skipping storage")
                return None

            memory_id = str(uuid.uuid4())

            # Canonical repository path
            if self.memory_repository is not None:
                from ai_karen_engine.services.database.repositories import MemoryItem
                item = MemoryItem(
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

            # Legacy path
            memory_entry = MemoryItem(
                id=memory_id,
                content=content,
                embedding=embedding,
                metadata=metadata or {},
                scope=scope,
                kind=kind,
                timestamp=time.time(),
            )

            # Insert vector
            if self.milvus_client:
                collection_name = self._get_collection_name(tenant_id)
                vector_metadata = {
                    "memory_id": memory_id,
                    "scope": scope,
                    "kind": kind,
                    "timestamp": memory_entry.timestamp,
                }
                if metadata:
                    vector_metadata.update(metadata)

                try:
                    await self.milvus_client.insert(
                        collection_name=collection_name,
                        vectors=[embedding.tolist()],
                        metadata=[vector_metadata],
                    )
                except Exception as e:
                    logger.warning(
                        f"Milvus insert failed (continuing with metadata only): {e}"
                    )
            else:
                logger.info("Milvus client unavailable – storing metadata only")

            # Store metadata (and embedding for fallback) in Postgres
            async with self.db_client.get_async_session() as session:
                record = TenantMemoryItem(
                    id=uuid.UUID(memory_id),
                    scope=scope,
                    kind=kind,
                    content=content,
                    embedding=embedding.tolist(),  # keep for local/fallback similarity
                    item_metadata=metadata or {},
                    created_at=datetime.utcnow(),
                )
                session.add(record)
                await session.commit()

            # Elasticsearch (optional, no-fail)
            if self.elasticsearch_client:
                await self._store_in_elasticsearch(tenant_id, memory_entry)

            # Redis cache (optional, best-effort)
            if self.redis_client:
                await self._cache_memory(tenant_id, memory_entry)

            # Update metrics
            self.metrics["memories_stored"] = int(self.metrics["memories_stored"]) + 1
            self.metrics["embeddings_generated"] = (
                int(self.metrics["embeddings_generated"]) + 1
            )
            self.metrics["avg_embedding_time"] = self._roll(
                float(self.metrics["avg_embedding_time"]), emb_dt
            )

            total_dt = time.time() - start_time
            logger.info(
                f"Stored memory {memory_id} for tenant={tenant_id} in {total_dt:.3f}s"
            )

            if self._metrics:
                try:
                    self._metrics.record_memory_commit(
                        status="success", decay_tier="", user_id="", org_id=""
                    )
                except Exception as metrics_err:
                    logger.warning(f"Failed to record memory commit metrics: {metrics_err}")

            return memory_id

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
        """
        Hybrid query: vector + metadata filters (+ full-text if available).
        Gracefully falls back to local cosine if Milvus is unavailable.
        """
        t0 = time.time()
        self.metrics["queries_total"] = int(self.metrics["queries_total"]) + 1
        cache_key = self._get_cache_key(tenant_id, query)

        try:
            # Canonical repository path
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

            # Legacy path
            # Ensure we have an embedding manager available
            await self._ensure_embedding_manager()
            # Cache
            if self.redis_client:
                cached = await self._get_cached_query(cache_key)
                if cached:
                    self.metrics["queries_cached"] = (
                        int(self.metrics["queries_cached"]) + 1
                    )
                    return cached

            # Query embedding
            if query.query_embedding is not None:
                q_emb = (
                    np.array(query.query_embedding)
                    if not isinstance(query.query_embedding, np.ndarray)
                    else query.query_embedding
                )
            else:
                q_emb_raw = await self.embedding_manager.get_embedding(query.text)
                q_emb = (
                    np.array(q_emb_raw)
                    if not isinstance(q_emb_raw, np.ndarray)
                    else q_emb_raw
                )

            # Metadata filter for vector DB
            metadata_filter = self._build_metadata_filter(query)

            # Vector search path
            if self.milvus_client:
                collection = self._get_collection_name(tenant_id)
                try:
                    vector_results = await self.milvus_client.search(
                        collection_name=collection,
                        query_vectors=[q_emb.tolist()],
                        top_k=max(1, query.top_k * 2),
                        metadata_filter=metadata_filter,
                    )
                    memory_ids, sim_scores = self._extract_vector_hits(
                        vector_results, query
                    )
                except Exception as e:
                    logger.warning(
                        f"Milvus search failed, falling back to local cosine: {e}"
                    )
                    memory_ids, sim_scores = await self._local_vector_fallback(
                        tenant_id, q_emb, query
                    )
            else:
                memory_ids, sim_scores = await self._local_vector_fallback(
                    tenant_id, q_emb, query
                )

            if not memory_ids:
                if self.redis_client:
                    await self._cache_query_result(cache_key, [])
                return []

            # Load full records
            memories = await self._get_memories_from_postgres(
                tenant_id, memory_ids, query.include_embeddings
            )

            # Additional filters
            memories = self._apply_filters(memories, query)

            # Recency weighting + sort
            memories = self._apply_recency_weighting(memories, sim_scores)

            # Trim and cache
            memories = memories[: query.top_k]
            if self.redis_client:
                await self._cache_query_result(cache_key, memories)

            # Metrics
            self.metrics["memories_retrieved"] = int(
                self.metrics["memories_retrieved"]
            ) + len(memories)
            dt = time.time() - t0
            self.metrics["avg_query_time"] = self._roll(
                float(self.metrics["avg_query_time"]), dt
            )

            return memories

        except Exception as e:
            logger.error(f"Failed to query memories for tenant {tenant_id}: {e}")
            raise

    async def delete_memory(
        self, tenant_id: Union[str, uuid.UUID], memory_id: str
    ) -> bool:
        """Delete a memory entry across vector DB, Postgres, ES, cache."""
        try:
            # Canonical repository path
            if self.memory_repository is not None:
                result = await self.memory_repository.delete_memory(memory_id, str(tenant_id))
                return result.success and bool(result.data)

            # Legacy path
            # Vector DB
            if self.milvus_client:
                try:
                    await self.milvus_client.delete(
                        collection_name=self._get_collection_name(tenant_id),
                        filter_expr=f"memory_id == '{memory_id}'",
                    )
                except Exception as e:
                    logger.warning(f"Milvus delete failed (continuing): {e}")
            else:
                logger.info("Milvus client unavailable – skipping vector delete")

            # Postgres
            async with self.db_client.get_async_session() as session:
                await session.execute(
                    delete(TenantMemoryItem).where(
                        TenantMemoryItem.id == uuid.UUID(memory_id)
                    )
                )
                await session.commit()

            # Elasticsearch
            if self.elasticsearch_client:
                await self._delete_from_elasticsearch(tenant_id, memory_id)

            # Cache
            if self.redis_client:
                await self._clear_memory_cache(tenant_id, memory_id)

            logger.info(f"Deleted memory {memory_id} for tenant={tenant_id}")
            return True

        except Exception as e:
            logger.error(
                f"Failed to delete memory {memory_id} for tenant {tenant_id}: {e}"
            )
            return False

    async def prune_expired_memories(self, tenant_id: Union[str, uuid.UUID]) -> int:
        """No-op placeholder: TenantMemoryItem has no TTL; retention handled elsewhere."""
        logger.info(
            "prune_expired_memories called – not applicable for memory_items table"
        )
        return 0

    async def _ensure_embedding_manager(self) -> None:
        """Lazily ensure an embedding manager instance is available.
        
        Attempts to obtain the global default embedding manager; if unavailable,
        provisions a local EmbeddingManager instance with best-effort init.
        """
        if getattr(self, "embedding_manager", None) is not None:
            return
        try:
            from ai_karen_engine.core.model_runtime import default_models
            try:
                # Idempotent init of global defaults
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
                    # Rely on internal fallbacks if initialization fails
                    pass
                self.embedding_manager = local_manager
            except Exception as e:
                logger.error(f"Failed to provision embedding manager fallback: {e}")
                self.embedding_manager = None

    async def get_memory_stats(
        self, tenant_id: Union[str, uuid.UUID]
    ) -> Dict[str, Any]:
        """Return simple stats (counts, recent activity, etc.)."""
        try:
            async with self.db_client.get_async_session() as session:
                # Total
                total_res = await session.execute(select(TenantMemoryItem.id))
                total_count = len(total_res.fetchall())

                # Recent (24h)
                recent_cutoff = datetime.utcnow() - timedelta(hours=24)
                recent_res = await session.execute(
                    select(TenantMemoryItem.id).where(
                        TenantMemoryItem.created_at > recent_cutoff
                    )
                )
                recent_count = len(recent_res.fetchall())

                # Scope/kind counts (use schema-qualified raw SQL for speed/clarity)
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
                "collection_name": self._get_collection_name(tenant_id),
                "metrics": dict(self.metrics),
            }

        except Exception as e:
            logger.error(f"Failed to get memory stats for tenant {tenant_id}: {e}")
            return {"error": str(e)}

    # -----------------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------------

    @staticmethod
    def _roll(current: float, x: float, alpha: float = 0.1) -> float:
        """Cheap exponential moving average."""
        return current * (1 - alpha) + x * alpha

    def _get_collection_name(self, tenant_id: Union[str, uuid.UUID]) -> str:
        return f"tenant_{str(tenant_id).replace('-', '_')}_memories"

    async def _check_surprise(
        self,
        tenant_id: Union[str, uuid.UUID],
        embedding: np.ndarray,
        scope: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> bool:
        """
        Check whether content is “surprising” (not a near-duplicate).
        - If Milvus unavailable, assume True (store) to keep the system usable.
        - Threshold semantics depend on KARI_MILVUS_METRIC_MODE env:
          * similarity: keep if max_similarity < threshold (less similar → store)
          * distance:   keep if min_distance > threshold (farther → store)
        """
        if self.disable_surprise_check:
            return True

        if not self.milvus_client:
            logger.warning(
                "Milvus client unavailable – skipping surprise check (store=True)"
            )
            return True

        try:
            collection = self._get_collection_name(tenant_id)
            md: Dict[str, Any] = {}
            if scope:
                md["scope"] = scope
            if kind:
                md["kind"] = kind

            results = await self.milvus_client.search(
                collection_name=collection,
                query_vectors=[embedding.tolist()],
                top_k=1,
                metadata_filter=md or None,
            )

            if not results or not results[0]:
                return True

            # Interpret metric carefully
            r0 = results[0][0]
            metric = float(getattr(r0, "distance", 0.0))

            if self.milvus_metric_mode == "distance":
                # lower distance = more similar; store only if far enough
                return metric > self.surprise_threshold
            else:
                # similarity mode: higher = more similar; store only if not too similar
                return metric < self.surprise_threshold

        except Exception as e:
            logger.warning(
                f"Surprise check failed, assuming surprising (store=True): {e}"
            )
            return True

    def _build_metadata_filter(self, query: MemoryQuery) -> Optional[Dict[str, Any]]:
        md: Dict[str, Any] = dict(query.metadata_filter)
        if query.user_id:
            md["user_id"] = query.user_id
        if query.session_id:
            md["session_id"] = query.session_id
        if query.conversation_id:
            md["conversation_id"] = query.conversation_id
        if query.tags:
            md["tags"] = query.tags
        if query.scope:
            md["scope"] = query.scope
        if query.kind:
            md["kind"] = query.kind
        return md or None

    async def _get_memories_from_postgres(
        self,
        tenant_id: Union[str, uuid.UUID],
        memory_ids: List[str],
        include_embeddings: bool = False,
    ) -> List[MemoryItem]:
        """Fetch memories by ID, preserving input order where possible."""
        if not memory_ids:
            return []

        try:
            async with self.db_client.get_async_session() as session:
                # Build a single sequence with stable typing for mypy/sqlalchemy
                ids_seq: Sequence[Any]
                try:
                    ids_seq = [uuid.UUID(m) for m in memory_ids]
                except Exception:
                    ids_seq = list(memory_ids)

                stmt = select(TenantMemoryItem).where(TenantMemoryItem.id.in_(ids_seq))
                result = await session.execute(stmt)

                # Use scalars() if present
                rows = (
                    result.scalars().all()
                    if hasattr(result, "scalars")
                    else [r[0] for r in result.fetchall()]
                )

                # Index by id for stable ordering
                by_id: Dict[str, MemoryItem] = {}
                for row in rows:
                    item = MemoryItem(
                        id=str(row.id),
                        content=row.content,
                        metadata=row.item_metadata or {},
                        scope=row.scope,
                        kind=row.kind,
                        timestamp=(
                            row.created_at.timestamp()
                            if row.created_at
                            else time.time()
                        ),
                    )
                    if include_embeddings and row.embedding is not None:
                        try:
                            item.embedding = np.array(row.embedding)
                        except Exception:
                            item.embedding = None
                    by_id[item.id] = item

                # Preserve order of memory_ids
                ordered = [by_id[mid] for mid in memory_ids if mid in by_id]
                return ordered

        except Exception as e:
            logger.error(f"Failed to fetch memories from Postgres: {e}")
            return []

    def _apply_filters(
        self, memories: List[MemoryEntry], query: MemoryQuery
    ) -> List[MemoryEntry]:
        filtered = memories

        # Explicit metadata filter
        if query.metadata_filter:
            filtered = [
                m
                for m in filtered
                if all(m.metadata.get(k) == v for k, v in query.metadata_filter.items())
            ]

        # user/session/conversation
        if query.user_id:
            filtered = [
                m for m in filtered if m.metadata.get("user_id") == query.user_id
            ]
        if query.session_id:
            filtered = [
                m for m in filtered if m.metadata.get("session_id") == query.session_id
            ]
        if query.conversation_id:
            filtered = [
                m
                for m in filtered
                if m.metadata.get("conversation_id") == query.conversation_id
            ]

        # tags (all required)
        if query.tags:
            filtered = [
                m
                for m in filtered
                if all(t in (m.metadata.get("tags") or []) for t in query.tags)
            ]

        # time range
        if query.time_range:
            start_dt, end_dt = query.time_range
            filtered = [
                m
                for m in filtered
                if start_dt.timestamp() <= m.timestamp <= end_dt.timestamp()
            ]

        return filtered

    def _apply_recency_weighting(
        self,
        memories: List[MemoryEntry],
        similarity_scores: Dict[str, float],
    ) -> List[MemoryEntry]:
        """Combine similarity and recency (EMA-like decay by age)."""
        now = time.time()
        alpha = self.recency_alpha

        for m in memories:
            base_sim = similarity_scores.get(m.id, 0.0)
            age_days = max(0.0, (now - m.timestamp) / (24 * 3600))
            recency_weight = float(np.exp(-alpha * age_days))
            m.similarity_score = base_sim * recency_weight

        return sorted(memories, key=lambda x: (x.similarity_score or 0.0), reverse=True)

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

    async def _store_in_elasticsearch(
        self, tenant_id: Union[str, uuid.UUID], memory: MemoryEntry
    ) -> None:
        if not self.elasticsearch_client:
            return
        try:
            index = f"tenant_{str(tenant_id).replace('-', '_')}_memories"
            doc = {
                "memory_id": memory.id,
                "content": memory.content,
                "metadata": memory.metadata,
                "timestamp": memory.timestamp,
                "scope": memory.scope,
                "kind": memory.kind,
            }
            await self.elasticsearch_client.index(index=index, id=memory.id, body=doc)
        except Exception as e:
            logger.debug(f"Elasticsearch index failed (non-fatal): {e}")

    async def _delete_from_elasticsearch(
        self, tenant_id: Union[str, uuid.UUID], memory_id: str
    ) -> None:
        if not self.elasticsearch_client:
            return
        try:
            index = f"tenant_{str(tenant_id).replace('-', '_')}_memories"
            await self.elasticsearch_client.delete(index=index, id=memory_id)
        except Exception as e:
            logger.debug(f"Elasticsearch delete failed (non-fatal): {e}")

    def _get_cache_key(
        self, tenant_id: Union[str, uuid.UUID], query: MemoryQuery
    ) -> str:
        q = json.dumps(query.to_dict(), sort_keys=True, default=str)
        h = hashlib.md5(q.encode("utf-8")).hexdigest()
        return f"memory_query:{tenant_id}:{h}"

    def _extract_vector_hits(
        self,
        vector_results: Any,
        query: MemoryQuery,
    ) -> Tuple[List[str], Dict[str, float]]:
        """
        Extract memory_ids and similarity scores from Milvus results.
        Respects self.milvus_metric_mode when building scores.
        """
        memory_ids: List[str] = []
        scores: Dict[str, float] = {}

        rows = vector_results[0] if vector_results else []
        if not rows:
            return memory_ids, scores

        for hit in rows:
            # hit.distance may be similarity or distance depending on index metric
            raw = float(getattr(hit, "distance", 0.0))
            memory_id = None
            # hit.entity might be dict-like
            ent = getattr(hit, "entity", None)
            if isinstance(ent, dict):
                memory_id = ent.get("memory_id")
            elif hasattr(hit, "id"):
                memory_id = str(getattr(hit, "id"))

            if not memory_id:
                # try raw fields
                try:
                    memory_id = hit.get("memory_id")  # type: ignore[attr-defined]
                except Exception:
                    pass

            if not memory_id:
                continue

            # Decide if we accept the hit based on threshold semantics
            accept = False
            score_for_sort = 0.0
            if self.milvus_metric_mode == "distance":
                # smaller = more similar
                accept = raw <= query.similarity_threshold
                # convert to similarity-like for sorting: higher better
                score_for_sort = 1.0 / (1e-6 + raw)
            else:
                # similarity mode: larger = more similar
                accept = raw >= query.similarity_threshold
                score_for_sort = raw

            if accept:
                memory_ids.append(memory_id)
                scores[memory_id] = score_for_sort

        return memory_ids, scores

    async def _local_vector_fallback(
        self,
        tenant_id: Union[str, uuid.UUID],
        q_emb: np.ndarray,
        query: MemoryQuery,
    ) -> Tuple[List[str], Dict[str, float]]:
        """
        No Milvus? Fall back to Postgres-stored embeddings with local cosine similarity.
        Scans up to self.fallback_scan_limit newest rows.
        """
        try:
            async with self.db_client.get_async_session() as session:
                # Fast path: newest N rows
                stmt = (
                    select(
                        TenantMemoryItem.id,
                        TenantMemoryItem.embedding,
                        TenantMemoryItem.item_metadata,
                        TenantMemoryItem.created_at,
                        TenantMemoryItem.scope,
                        TenantMemoryItem.kind,
                    )
                    .order_by(TenantMemoryItem.created_at.desc())
                    .limit(self.fallback_scan_limit)
                )
                res = await session.execute(stmt)
                rows = res.all()

            ids: List[str] = []
            sims: Dict[str, float] = {}
            ranked_candidates: List[Tuple[str, float]] = []
            q_norm = np.linalg.norm(q_emb) + 1e-9
            effective_threshold = min(
                query.similarity_threshold,
                self.fallback_similarity_threshold,
            )

            # Pre-filter by metadata if provided (cheap dict checks)
            md_filter = self._build_metadata_filter(query) or {}

            for mid, emb, md, created_at, scope, kind in rows:
                # Metadata filter
                if md_filter and not self._md_match(md or {}, md_filter):
                    continue

                if not emb:
                    continue
                try:
                    v = np.array(emb, dtype=np.float32)
                except Exception:
                    continue
                v_norm = np.linalg.norm(v) + 1e-9
                cos = float(np.dot(q_emb, v) / (q_norm * v_norm))
                sid = str(mid)
                ranked_candidates.append((sid, cos))

                # similarity threshold: in local fallback treat threshold as cosine floor
                if cos >= effective_threshold:
                    ids.append(sid)
                    sims[sid] = cos

            if not ids and ranked_candidates:
                fallback_hits = sorted(
                    ranked_candidates,
                    key=lambda item: item[1],
                    reverse=True,
                )[: max(1, query.top_k * 2)]
                ids = [sid for sid, _score in fallback_hits if _score > 0.0]
                sims = {sid: score for sid, score in fallback_hits if score > 0.0}

            # Keep top 2x for downstream filters/sorting, preserve similarity dict
            if len(ids) > query.top_k * 2:
                ids_sorted = sorted(ids, key=lambda _id: sims[_id], reverse=True)[
                    : query.top_k * 2
                ]
                sims = {k: sims[k] for k in ids_sorted}
                ids = ids_sorted

            return ids, sims

        except Exception as e:
            logger.warning(f"Local vector fallback failed, returning empty: {e}")
            return [], {}

    @staticmethod
    def _md_match(candidate: Dict[str, Any], required: Dict[str, Any]) -> bool:
        """Simple key==value matching; lists must contain all items."""
        for k, v in required.items():
            cv = candidate.get(k)
            if isinstance(v, list):
                if not isinstance(cv, list):
                    return False
                if not all(item in (cv or []) for item in v):
                    return False
            else:
                if cv != v:
                    return False
        return True


__all__ = [
    "MemoryManager",
    "MemoryItem",
    "MemoryEntry",
    "MemoryQuery",
]
