"""PostgreSQL-backed conversation repository implementation.

Converges duplicate conversation stores (conversations + chat_conversations)
behind a single canonical interface with tenant scoping.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_karen_engine.services.database.repositories.conversation_repository import (
    Conversation,
    ConversationQuery,
    ConversationRepository,
    Message,
    RepositoryResult,
)

logger = logging.getLogger(__name__)


class PostgresConversationRepository(ConversationRepository):
    """PostgreSQL conversation repository.

    Canonical source is the `conversations` + `messages` tables.
    During convergence, `chat_conversations` + `chat_messages` are
    also supported for read-through.
    """

    def __init__(self, session_factory, use_chat_tables: bool = False):
        self._session_factory = session_factory
        self._conversation_table = "chat_conversations" if use_chat_tables else "conversations"
        self._message_table = "chat_messages" if use_chat_tables else "messages"

    async def _session(self) -> AsyncSession:
        return self._session_factory()

    async def health_check(self) -> RepositoryResult:
        try:
            async with await self._session() as session:
                await session.execute(text("SELECT 1"))
            return RepositoryResult(success=True)
        except Exception as exc:
            logger.error("ConversationRepository health check failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def create_conversation(self, conversation: Conversation) -> RepositoryResult[str]:
        start = time.perf_counter()
        try:
            async with await self._session() as session:
                await session.execute(
                    text(
                        f"""
                        INSERT INTO {self._conversation_table}
                            (conversation_id, tenant_id, user_id, title, is_active,
                             summary, tags, conversation_metadata, created_at, updated_at)
                        VALUES
                            (:id, :tenant_id, :user_id, :title, :is_active,
                             :summary, :tags, :metadata, :created_at, :updated_at)
                        """
                    ),
                    {
                        "id": conversation.id,
                        "tenant_id": conversation.tenant_id,
                        "user_id": conversation.user_id,
                        "title": conversation.title,
                        "is_active": conversation.is_active,
                        "summary": conversation.summary,
                        "tags": conversation.tags,
                        "metadata": json.dumps(conversation.metadata),
                        "created_at": conversation.created_at,
                        "updated_at": conversation.updated_at,
                    },
                )
                await session.commit()
                latency = time.perf_counter() - start
                logger.debug("create_conversation id=%s latency_ms=%.2f", conversation.id, latency * 1000)
                return RepositoryResult(success=True, data=conversation.id)
        except Exception as exc:
            logger.error("create_conversation failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def get_conversation(self, conversation_id: str, tenant_id: str) -> RepositoryResult[Optional[Conversation]]:
        try:
            async with await self._session() as session:
                result = await session.execute(
                    text(
                        f"""
                        SELECT conversation_id, tenant_id, user_id, title, is_active,
                               summary, tags, conversation_metadata, created_at, updated_at
                        FROM {self._conversation_table}
                        WHERE conversation_id = :id AND tenant_id = :tenant_id
                        """
                    ),
                    {"id": conversation_id, "tenant_id": tenant_id},
                )
                row = result.fetchone()
                if not row:
                    return RepositoryResult(success=True, data=None)
                conv = self._row_to_conversation(row)
                return RepositoryResult(success=True, data=conv)
        except Exception as exc:
            logger.error("get_conversation failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def list_conversations(self, query: ConversationQuery) -> RepositoryResult[Sequence[Conversation]]:
        start = time.perf_counter()
        try:
            clauses = ["tenant_id = :tenant_id"]
            params: Dict[str, Any] = {"tenant_id": query.tenant_id}

            if query.user_id:
                clauses.append("user_id = :user_id")
                params["user_id"] = query.user_id
            if query.is_active is not None:
                clauses.append("is_active = :is_active")
                params["is_active"] = query.is_active
            if query.tags:
                clauses.append("tags @> :tags")
                params["tags"] = query.tags
            if query.created_after:
                clauses.append("created_at >= :created_after")
                params["created_after"] = query.created_after

            where = " AND ".join(clauses)
            sql = f"""
                SELECT conversation_id, tenant_id, user_id, title, is_active,
                       summary, tags, conversation_metadata, created_at, updated_at
                FROM {self._conversation_table}
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT :limit OFFSET :offset
            """
            params["limit"] = query.limit
            params["offset"] = query.offset

            async with await self._session() as session:
                result = await session.execute(text(sql), params)
                rows = result.fetchall()
                conversations = [self._row_to_conversation(row) for row in rows]
                latency = time.perf_counter() - start
                logger.debug("list_conversations returned=%d latency_ms=%.2f", len(conversations), latency * 1000)
                return RepositoryResult(success=True, data=conversations)
        except Exception as exc:
            logger.error("list_conversations failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def update_conversation(self, conversation: Conversation) -> RepositoryResult[bool]:
        start = time.perf_counter()
        try:
            async with await self._session() as session:
                await session.execute(
                    text(
                        f"""
                        UPDATE {self._conversation_table}
                        SET title = :title,
                            is_active = :is_active,
                            summary = :summary,
                            tags = :tags,
                            conversation_metadata = :metadata,
                            updated_at = :updated_at
                        WHERE conversation_id = :id AND tenant_id = :tenant_id
                        """
                    ),
                    {
                        "id": conversation.id,
                        "tenant_id": conversation.tenant_id,
                        "title": conversation.title,
                        "is_active": conversation.is_active,
                        "summary": conversation.summary,
                        "tags": conversation.tags,
                        "metadata": json.dumps(conversation.metadata),
                        "updated_at": conversation.updated_at,
                    },
                )
                await session.commit()
                latency = time.perf_counter() - start
                logger.debug("update_conversation id=%s latency_ms=%.2f", conversation.id, latency * 1000)
                return RepositoryResult(success=True, data=True)
        except Exception as exc:
            logger.error("update_conversation failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def delete_conversation(self, conversation_id: str, tenant_id: str) -> RepositoryResult[bool]:
        start = time.perf_counter()
        try:
            async with await self._session() as session:
                await session.execute(
                    text(
                        f"""
                        DELETE FROM {self._conversation_table}
                        WHERE conversation_id = :id AND tenant_id = :tenant_id
                        """
                    ),
                    {"id": conversation_id, "tenant_id": tenant_id},
                )
                await session.commit()
                latency = time.perf_counter() - start
                logger.debug("delete_conversation id=%s latency_ms=%.2f", conversation_id, latency * 1000)
                return RepositoryResult(success=True, data=True)
        except Exception as exc:
            logger.error("delete_conversation failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def add_message(self, message: Message) -> RepositoryResult[str]:
        start = time.perf_counter()
        try:
            async with await self._session() as session:
                await session.execute(
                    text(
                        f"""
                        INSERT INTO {self._message_table}
                            (message_id, conversation_id, role, content,
                             message_metadata, created_at, updated_at)
                        VALUES
                            (:id, :conversation_id, :role, :content,
                             :metadata, :created_at, :updated_at)
                        """
                    ),
                    {
                        "id": message.id,
                        "conversation_id": message.conversation_id,
                        "role": message.role,
                        "content": message.content,
                        "metadata": json.dumps(message.metadata),
                        "created_at": message.created_at,
                        "updated_at": message.updated_at,
                    },
                )
                await session.commit()
                latency = time.perf_counter() - start
                logger.debug("add_message id=%s latency_ms=%.2f", message.id, latency * 1000)
                return RepositoryResult(success=True, data=message.id)
        except Exception as exc:
            logger.error("add_message failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def get_messages(
        self, conversation_id: str, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> RepositoryResult[List[Message]]:
        start = time.perf_counter()
        try:
            async with await self._session() as session:
                result = await session.execute(
                    text(
                        f"""
                        SELECT m.message_id, m.conversation_id, m.role, m.content,
                               m.message_metadata, m.created_at, m.updated_at,
                               c.tenant_id
                        FROM {self._message_table} m
                        JOIN {self._conversation_table} c ON m.conversation_id = c.conversation_id
                        WHERE m.conversation_id = :conversation_id AND c.tenant_id = :tenant_id
                        ORDER BY m.created_at ASC
                        LIMIT :limit OFFSET :offset
                        """
                    ),
                    {
                        "conversation_id": conversation_id,
                        "tenant_id": tenant_id,
                        "limit": limit,
                        "offset": offset,
                    },
                )
                rows = result.fetchall()
                messages = [self._row_to_message(row) for row in rows]
                latency = time.perf_counter() - start
                logger.debug("get_messages conversation_id=%s returned=%d latency_ms=%.2f", conversation_id, len(messages), latency * 1000)
                return RepositoryResult(success=True, data=messages)
        except Exception as exc:
            logger.error("get_messages failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def update_message(self, message: Message) -> RepositoryResult[bool]:
        start = time.perf_counter()
        try:
            async with await self._session() as session:
                await session.execute(
                    text(
                        f"""
                        UPDATE {self._message_table}
                        SET content = :content,
                            message_metadata = :metadata,
                            updated_at = :updated_at
                        WHERE message_id = :id
                        """
                    ),
                    {
                        "id": message.id,
                        "content": message.content,
                        "metadata": json.dumps(message.metadata),
                        "updated_at": message.updated_at,
                    },
                )
                await session.commit()
                latency = time.perf_counter() - start
                logger.debug("update_message id=%s latency_ms=%.2f", message.id, latency * 1000)
                return RepositoryResult(success=True, data=True)
        except Exception as exc:
            logger.error("update_message failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def delete_message(self, message_id: str, tenant_id: str) -> RepositoryResult[bool]:
        start = time.perf_counter()
        try:
            async with await self._session() as session:
                await session.execute(
                    text(
                        f"""
                        DELETE FROM {self._message_table}
                        WHERE message_id = :id
                          AND conversation_id IN (
                              SELECT conversation_id FROM {self._conversation_table}
                              WHERE tenant_id = :tenant_id
                          )
                        """
                    ),
                    {"id": message_id, "tenant_id": tenant_id},
                )
                await session.commit()
                latency = time.perf_counter() - start
                logger.debug("delete_message id=%s latency_ms=%.2f", message_id, latency * 1000)
                return RepositoryResult(success=True, data=True)
        except Exception as exc:
            logger.error("delete_message failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    def _row_to_conversation(self, row: Any) -> Conversation:
        return Conversation(
            id=str(row.conversation_id),
            tenant_id=str(row.tenant_id) if row.tenant_id else "",
            user_id=str(row.user_id) if row.user_id else "",
            title=row.title,
            is_active=row.is_active if row.is_active is not None else True,
            summary=row.summary,
            tags=row.tags or [],
            metadata=json.loads(row.conversation_metadata) if row.conversation_metadata else {},
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _row_to_message(self, row: Any) -> Message:
        return Message(
            id=str(row.message_id),
            conversation_id=str(row.conversation_id),
            tenant_id=str(row.tenant_id) if row.tenant_id else "",
            role=str(row.role),
            content=str(row.content),
            metadata=json.loads(row.message_metadata) if row.message_metadata else {},
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
