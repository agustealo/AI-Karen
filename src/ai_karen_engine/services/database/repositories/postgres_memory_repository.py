"""PostgreSQL-backed memory repository implementation.

Uses pgvector for semantic search, PostgreSQL FTS for lexical search,
and NeuroRecall-compatible signal envelopes for hybrid ranking.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_karen_engine.services.database.repositories.memory_repository import (
    HybridSearchResult,
    MemoryItem,
    MemoryQuery,
    MemoryRepository,
    RepositoryResult,
)

logger = logging.getLogger(__name__)


class PostgresMemoryRepository(MemoryRepository):
    """PostgreSQL + pgvector + FTS memory repository.

    Does NOT expose pgvector, Milvus, or Elasticsearch types to callers.
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def _session(self) -> AsyncSession:
        return self._session_factory()

    async def health_check(self) -> RepositoryResult:
        try:
            async with await self._session() as session:
                await session.execute(text("SELECT 1"))
            return RepositoryResult(success=True)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("MemoryRepository health check failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def store_memory(self, item: MemoryItem) -> RepositoryResult[str]:
        start = time.perf_counter()
        try:
            async with await self._session() as session:
                embedding_vector_json = json.dumps(item.embedding) if item.embedding else None
                content_tsv = item.content
                user_id = item.user_id or ""
                result = await session.execute(
                    text(
                        """
                        INSERT INTO memory_items
                            (id, tenant_id, user_id, conversation_id, scope, kind,
                             content, content_tsv, embedding_vector,
                             importance, confidence, source_type, source_ref,
                             expires_at, metadata, created_at, updated_at)
                        VALUES
                            (:id, :tenant_id, :user_id, :conversation_id, :scope, :kind,
                             :content, :content_tsv, :embedding_vector,
                             :importance, :confidence, :source_type, :source_ref,
                             :expires_at, :metadata, :created_at, :updated_at)
                        ON CONFLICT (id) DO UPDATE SET
                            content = EXCLUDED.content,
                            embedding_vector = EXCLUDED.embedding_vector,
                            importance = EXCLUDED.importance,
                            confidence = EXCLUDED.confidence,
                            updated_at = EXCLUDED.updated_at
                        """
                    ),
                    {
                        "id": item.id,
                        "tenant_id": item.tenant_id,
                        "user_id": user_id,
                        "conversation_id": item.conversation_id,
                        "scope": item.memory_type,
                        "kind": item.memory_type,
                        "content": item.content,
                        "content_tsv": content_tsv,
                        "embedding_vector": embedding_vector_json,
                        "importance": item.importance,
                        "confidence": item.confidence,
                        "source_type": item.source_type,
                        "source_ref": item.source_ref,
                        "expires_at": item.expires_at,
                        "metadata": json.dumps(item.metadata),
                        "created_at": item.created_at,
                        "updated_at": item.updated_at,
                    },
                )
                await session.commit()
                latency = time.perf_counter() - start
                logger.debug("store_memory id=%s latency_ms=%.2f", item.id, latency * 1000)
                return RepositoryResult(success=True, data=item.id)
        except Exception as exc:
            logger.error("store_memory failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def update_memory(self, item: MemoryItem) -> RepositoryResult[bool]:
        start = time.perf_counter()
        try:
            async with await self._session() as session:
                embedding_vector_json = json.dumps(item.embedding) if item.embedding else None
                await session.execute(
                    text(
                        """
                        UPDATE memory_items
                        SET content = :content,
                            embedding_vector = :embedding_vector,
                            importance = :importance,
                            confidence = :confidence,
                            updated_at = :updated_at,
                            expires_at = :expires_at,
                            metadata = :metadata
                        WHERE id = :id AND tenant_id = :tenant_id
                        """
                    ),
                    {
                        "id": item.id,
                        "tenant_id": item.tenant_id,
                        "content": item.content,
                        "embedding_vector": embedding_vector_json,
                        "importance": item.importance,
                        "confidence": item.confidence,
                        "updated_at": item.updated_at,
                        "expires_at": item.expires_at,
                        "metadata": json.dumps(item.metadata),
                    },
                )
                await session.commit()
                latency = time.perf_counter() - start
                logger.debug("update_memory id=%s latency_ms=%.2f", item.id, latency * 1000)
                return RepositoryResult(success=True, data=True)
        except Exception as exc:
            logger.error("update_memory failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def delete_memory(self, memory_id: str, tenant_id: str) -> RepositoryResult[bool]:
        start = time.perf_counter()
        try:
            async with await self._session() as session:
                await session.execute(
                    text("DELETE FROM memory_items WHERE id = :id AND tenant_id = :tenant_id"),
                    {"id": memory_id, "tenant_id": tenant_id},
                )
                await session.commit()
                latency = time.perf_counter() - start
                logger.debug("delete_memory id=%s latency_ms=%.2f", memory_id, latency * 1000)
                return RepositoryResult(success=True, data=True)
        except Exception as exc:
            logger.error("delete_memory failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def get_memory(self, memory_id: str, tenant_id: str) -> RepositoryResult[Optional[MemoryItem]]:
        try:
            async with await self._session() as session:
                result = await session.execute(
                    text(
                        """
                        SELECT id, tenant_id, user_id, conversation_id, scope, kind,
                               content, embedding_vector, importance, confidence,
                               source_type, source_ref, expires_at, metadata,
                               created_at, updated_at
                        FROM memory_items
                        WHERE id = :id AND tenant_id = :tenant_id
                        """
                    ),
                    {"id": memory_id, "tenant_id": tenant_id},
                )
                row = result.fetchone()
                if not row:
                    return RepositoryResult(success=True, data=None)
                item = self._row_to_item(row)
                return RepositoryResult(success=True, data=item)
        except Exception as exc:
            logger.error("get_memory failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def list_by_scope(self, query: MemoryQuery) -> RepositoryResult[List[MemoryItem]]:
        start = time.perf_counter()
        try:
            clauses = ["tenant_id = :tenant_id"]
            params: Dict[str, Any] = {"tenant_id": query.tenant_id}

            if query.user_id:
                clauses.append("user_id = :user_id")
                params["user_id"] = query.user_id
            if query.conversation_id:
                clauses.append("conversation_id = :conversation_id")
                params["conversation_id"] = query.conversation_id
            if query.memory_type:
                clauses.append("kind = :kind")
                params["kind"] = query.memory_type
            if query.time_range:
                clauses.append("created_at >= :time_from AND created_at <= :time_to")
                params["time_from"] = query.time_range[0]
                params["time_to"] = query.time_range[1]
            if query.tags:
                clauses.append("tags @> :tags")
                params["tags"] = query.tags

            where = " AND ".join(clauses)
            sql = f"""
                SELECT id, tenant_id, user_id, conversation_id, scope, kind,
                       content, embedding_vector, importance, confidence,
                       source_type, source_ref, expires_at, metadata,
                       created_at, updated_at
                FROM memory_items
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """
            params["limit"] = query.top_k
            params["offset"] = 0

            async with await self._session() as session:
                result = await session.execute(text(sql), params)
                rows = result.fetchall()
                items = [self._row_to_item(row) for row in rows]
                latency = time.perf_counter() - start
                logger.debug("list_by_scope returned=%d latency_ms=%.2f", len(items), latency * 1000)
                return RepositoryResult(success=True, data=items)
        except Exception as exc:
            logger.error("list_by_scope failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def search_semantic(
        self, query: MemoryQuery, embedding: List[float]
    ) -> RepositoryResult[List[HybridSearchResult]]:
        start = time.perf_counter()
        try:
            embedding_json = json.dumps(embedding)
            clauses = ["tenant_id = :tenant_id", "embedding_vector IS NOT NULL"]
            params: Dict[str, Any] = {"tenant_id": query.tenant_id, "embedding": embedding_json}

            if query.user_id:
                clauses.append("user_id = :user_id")
                params["user_id"] = query.user_id
            if query.conversation_id:
                clauses.append("conversation_id = :conversation_id")
                params["conversation_id"] = query.conversation_id
            if query.memory_type:
                clauses.append("kind = :kind")
                params["kind"] = query.memory_type

            where = " AND ".join(clauses)
            sql = f"""
                SELECT id, tenant_id, user_id, conversation_id, scope, kind,
                       content, embedding_vector, importance, confidence,
                       source_type, source_ref, expires_at, metadata,
                       created_at, updated_at,
                       1 - (embedding_vector <=> :embedding::vector) AS semantic_score
                FROM memory_items
                WHERE {where}
                ORDER BY embedding_vector <=> :embedding::vector
                LIMIT :limit
            """
            params["limit"] = query.top_k

            async with await self._session() as session:
                result = await session.execute(text(sql), params)
                rows = result.fetchall()
                items = []
                for row in rows:
                    item = self._row_to_item(row)
                    semantic_score = float(row.semantic_score or 0.0)
                    items.append(
                        HybridSearchResult(
                            item=item,
                            semantic_score=semantic_score,
                            lexical_score=0.0,
                            combined_score=semantic_score,
                            signals={"semantic": semantic_score},
                        )
                    )
                latency = time.perf_counter() - start
                logger.debug("search_semantic returned=%d latency_ms=%.2f", len(items), latency * 1000)
                return RepositoryResult(success=True, data=items)
        except Exception as exc:
            logger.error("search_semantic failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def search_keyword(self, query: MemoryQuery) -> RepositoryResult[List[HybridSearchResult]]:
        start = time.perf_counter()
        try:
            clauses = ["tenant_id = :tenant_id"]
            params: Dict[str, Any] = {"tenant_id": query.tenant_id, "query": query.text}

            if query.user_id:
                clauses.append("user_id = :user_id")
                params["user_id"] = query.user_id
            if query.conversation_id:
                clauses.append("conversation_id = :conversation_id")
                params["conversation_id"] = query.conversation_id
            if query.memory_type:
                clauses.append("kind = :kind")
                params["kind"] = query.memory_type

            where = " AND ".join(clauses)
            sql = f"""
                SELECT id, tenant_id, user_id, conversation_id, scope, kind,
                       content, embedding_vector, importance, confidence,
                       source_type, source_ref, expires_at, metadata,
                       created_at, updated_at,
                       ts_rank(content_tsv, websearch_to_tsquery('english', :query)) AS lexical_score
                FROM memory_items
                WHERE {where}
                  AND content_tsv @@ websearch_to_tsquery('english', :query)
                ORDER BY lexical_score DESC
                LIMIT :limit
            """
            params["limit"] = query.top_k

            async with await self._session() as session:
                result = await session.execute(text(sql), params)
                rows = result.fetchall()
                items = []
                for row in rows:
                    item = self._row_to_item(row)
                    lexical_score = float(row.lexical_score or 0.0)
                    items.append(
                        HybridSearchResult(
                            item=item,
                            semantic_score=0.0,
                            lexical_score=lexical_score,
                            combined_score=lexical_score,
                            signals={"lexical": lexical_score},
                        )
                    )
                latency = time.perf_counter() - start
                logger.debug("search_keyword returned=%d latency_ms=%.2f", len(items), latency * 1000)
                return RepositoryResult(success=True, data=items)
        except Exception as exc:
            logger.error("search_keyword failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def search_hybrid(
        self, query: MemoryQuery, embedding: List[float]
    ) -> RepositoryResult[List[HybridSearchResult]]:
        start = time.perf_counter()
        try:
            embedding_json = json.dumps(embedding)
            clauses = ["tenant_id = :tenant_id", "embedding_vector IS NOT NULL"]
            params: Dict[str, Any] = {
                "tenant_id": query.tenant_id,
                "embedding": embedding_json,
                "query": query.text,
            }

            if query.user_id:
                clauses.append("user_id = :user_id")
                params["user_id"] = query.user_id
            if query.conversation_id:
                clauses.append("conversation_id = :conversation_id")
                params["conversation_id"] = query.conversation_id
            if query.memory_type:
                clauses.append("kind = :kind")
                params["kind"] = query.memory_type

            where = " AND ".join(clauses)
            sql = f"""
                SELECT id, tenant_id, user_id, conversation_id, scope, kind,
                       content, embedding_vector, importance, confidence,
                       source_type, source_ref, expires_at, metadata,
                       created_at, updated_at,
                       1 - (embedding_vector <=> :embedding::vector) AS semantic_score,
                       ts_rank(content_tsv, websearch_to_tsquery('english', :query)) AS lexical_score
                FROM memory_items
                WHERE {where}
                  AND content_tsv @@ websearch_to_tsquery('english', :query)
                ORDER BY
                    (0.6 * (1 - (embedding_vector <=> :embedding::vector))
                     + 0.4 * ts_rank(content_tsv, websearch_to_tsquery('english', :query))) DESC
                LIMIT :limit
            """
            params["limit"] = query.top_k

            async with await self._session() as session:
                result = await session.execute(text(sql), params)
                rows = result.fetchall()
                items = []
                for row in rows:
                    item = self._row_to_item(row)
                    semantic_score = float(row.semantic_score or 0.0)
                    lexical_score = float(row.lexical_score or 0.0)
                    combined = 0.6 * semantic_score + 0.4 * lexical_score
                    items.append(
                        HybridSearchResult(
                            item=item,
                            semantic_score=semantic_score,
                            lexical_score=lexical_score,
                            combined_score=combined,
                            signals={"semantic": semantic_score, "lexical": lexical_score},
                        )
                    )
                latency = time.perf_counter() - start
                logger.debug("search_hybrid returned=%d latency_ms=%.2f", len(items), latency * 1000)
                return RepositoryResult(success=True, data=items)
        except Exception as exc:
            logger.error("search_hybrid failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def count(self, tenant_id: str, user_id: Optional[str] = None) -> RepositoryResult[int]:
        try:
            async with await self._session() as session:
                sql = "SELECT COUNT(*) FROM memory_items WHERE tenant_id = :tenant_id"
                params: Dict[str, Any] = {"tenant_id": tenant_id}
                if user_id:
                    sql += " AND user_id = :user_id"
                    params["user_id"] = user_id
                result = await session.execute(text(sql), params)
                count = result.scalar_one()
                return RepositoryResult(success=True, data=int(count))
        except Exception as exc:
            logger.error("count failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    def _row_to_item(self, row: Any) -> MemoryItem:
        embedding = None
        if row.embedding_vector:
            try:
                embedding = json.loads(row.embedding_vector)
            except (TypeError, ValueError):
                embedding = None
        return MemoryItem(
            id=str(row.id),
            tenant_id=str(row.tenant_id) if row.tenant_id else "",
            user_id=str(row.user_id) if row.user_id else "",
            conversation_id=str(row.conversation_id) if row.conversation_id else None,
            memory_type=str(row.kind or row.scope or "episodic"),
            content=str(row.content or ""),
            embedding=embedding,
            importance=float(row.importance or 0.5),
            confidence=float(row.confidence or 1.0),
            source_type=str(row.source_type or "system"),
            source_ref=str(row.source_ref) if row.source_ref else None,
            expires_at=row.expires_at,
            metadata=json.loads(row.metadata) if row.metadata else {},
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
