"""
Database operations module for optimized database queries and operations.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple, Union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, and_, or_, desc, func, text
from sqlalchemy.orm import selectinload, joinedload

from .models import (
    ChatConversation,
    ChatMessage,
    ChatSession,
    MessageAttachment,
    ChatProviderConfiguration,
)

logger = logging.getLogger(__name__)


class DatabaseOperations:
    """Optimized database operations for chat system."""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def get_conversation_with_messages(
        self,
        conversation_id: str,
        user_id: str,
        message_limit: int = 100,
        message_offset: int = 0,
        include_attachments: bool = True,
    ) -> Optional[ChatConversation]:
        """Get conversation with messages efficiently."""
        try:
            query = select(ChatConversation).where(
                and_(
                    ChatConversation.id == conversation_id,
                    ChatConversation.user_id == user_id,
                )
            )

            # Get conversation first
            result = await self.db_session.execute(query)
            conversation = result.scalar_one_or_none()

            if not conversation:
                return None

            # Get messages separately with pagination
            messages_query = (
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(ChatMessage.created_at)
            )

            if include_attachments:
                messages_query = messages_query.options(
                    selectinload(ChatMessage.attachments)
                )

            messages_query = messages_query.limit(message_limit).offset(message_offset)
            messages_result = await self.db_session.execute(messages_query)
            conversation.messages = list(messages_result.scalars().all())

            return conversation

        except Exception as e:
            logger.error(f"Failed to get conversation with messages: {e}")
            raise

    async def get_messages_with_pagination(
        self,
        conversation_id: str,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
        include_attachments: bool = True,
    ) -> Tuple[List[ChatMessage], int]:
        """Get messages with pagination and total count."""
        try:
            # Verify conversation ownership
            conv_result = await self.db_session.execute(
                select(ChatConversation.id).where(
                    and_(
                        ChatConversation.id == conversation_id,
                        ChatConversation.user_id == user_id,
                    )
                )
            )
            if not conv_result.scalar_one_or_none():
                return [], 0

            # Get total count
            count_result = await self.db_session.execute(
                select(func.count(ChatMessage.id)).where(
                    ChatMessage.conversation_id == conversation_id
                )
            )
            total = count_result.scalar()

            # Get messages
            query = (
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(ChatMessage.created_at)
            )

            if include_attachments:
                query = query.options(selectinload(ChatMessage.attachments))

            query = query.limit(limit).offset(offset)

            result = await self.db_session.execute(query)
            messages = result.scalars().all()

            return list(messages), total or 0

        except Exception as e:
            logger.error(f"Failed to get messages with pagination: {e}")
            raise

    async def search_messages_fulltext(
        self,
        user_id: str,
        query_text: str,
        conversation_ids: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[ChatMessage], int]:
        """Full-text search across messages."""
        try:
            # Build base query
            base_query = (
                select(ChatMessage)
                .join(ChatConversation)
                .where(
                    and_(
                        ChatConversation.user_id == user_id,
                        ChatMessage.content.ilike(f"%{query_text}%"),
                    )
                )
            )

            # Filter by conversation IDs if provided
            if conversation_ids:
                base_query = base_query.where(
                    ChatMessage.conversation_id.in_(conversation_ids)
                )

            # Get total count
            count_query = select(func.count()).select_from(base_query.subquery())
            total_result = await self.db_session.execute(count_query)
            total = total_result.scalar() or 0

            # Get results with conversation data
            result = await self.db_session.execute(
                base_query.options(selectinload(ChatMessage.attachments))
                .order_by(desc(ChatMessage.created_at))
                .limit(limit)
                .offset(offset)
            )
            messages = result.scalars().all()

            return list(messages), total

        except Exception as e:
            logger.error(f"Failed to search messages: {e}")
            raise

    async def get_conversation_threads(
        self, conversation_id: str, user_id: str, root_message_id: Optional[str] = None
    ) -> List[ChatMessage]:
        """Get message threads for a conversation."""
        try:
            # Verify conversation ownership
            conv_result = await self.db_session.execute(
                select(ChatConversation.id).where(
                    and_(
                        ChatConversation.id == conversation_id,
                        ChatConversation.user_id == user_id,
                    )
                )
            )
            if not conv_result.scalar_one_or_none():
                return []

            # Build thread query
            if root_message_id:
                # Get specific thread
                query = select(ChatMessage).where(
                    and_(
                        ChatMessage.conversation_id == conversation_id,
                        or_(
                            ChatMessage.id == root_message_id,
                            ChatMessage.parent_message_id == root_message_id,
                        ),
                    )
                )
            else:
                # Get all root messages (threads)
                query = select(ChatMessage).where(
                    and_(
                        ChatMessage.conversation_id == conversation_id,
                        ChatMessage.parent_message_id.is_(None),
                    )
                )

            query = query.order_by(ChatMessage.created_at)

            result = await self.db_session.execute(query)
            return list(result.scalars().all())

        except Exception as e:
            logger.error(f"Failed to get conversation threads: {e}")
            raise

    async def get_user_conversation_stats(
        self, user_id: str, days: int = 30
    ) -> Dict[str, Any]:
        """Get comprehensive conversation statistics."""
        try:
            date_from = datetime.utcnow() - timedelta(days=days)

            # Conversation stats
            conv_stats = await self.db_session.execute(
                select(
                    func.count(ChatConversation.id).label("total"),
                    func.count(func.distinct(ChatConversation.provider_id)).label(
                        "unique_providers"
                    ),
                    func.avg(ChatConversation.message_count).label("avg_messages"),
                    func.sum(ChatConversation.message_count).label("total_messages"),
                ).where(
                    and_(
                        ChatConversation.user_id == user_id,
                        ChatConversation.created_at >= date_from,
                    )
                )
            )
            conv_result = (
                conv_stats.first()
                or type(
                    "obj",
                    (object,),
                    {
                        "total": 0,
                        "unique_providers": 0,
                        "avg_messages": 0,
                        "total_messages": 0,
                    },
                )()
            )

            # Message stats by role
            message_stats = await self.db_session.execute(
                select(
                    ChatMessage.role,
                    func.count(ChatMessage.id).label("count"),
                    func.avg(ChatMessage.token_count).label("avg_tokens"),
                )
                .join(ChatConversation)
                .where(
                    and_(
                        ChatConversation.user_id == user_id,
                        ChatMessage.created_at >= date_from,
                    )
                )
                .group_by(ChatMessage.role)
            )
            message_results = message_stats.all()

            # Provider usage
            provider_stats = await self.db_session.execute(
                select(
                    ChatConversation.provider_id,
                    func.count(ChatConversation.id).label("conversation_count"),
                    func.sum(ChatConversation.message_count).label("message_count"),
                )
                .where(
                    and_(
                        ChatConversation.user_id == user_id,
                        ChatConversation.created_at >= date_from,
                    )
                )
                .group_by(ChatConversation.provider_id)
                .order_by(desc("conversation_count"))
            )
            provider_results = provider_stats.all()

            # Daily activity
            daily_activity = await self.db_session.execute(
                select(
                    func.date(ChatConversation.created_at).label("date"),
                    func.count(ChatConversation.id).label("conversations"),
                    func.count(ChatMessage.id).label("messages"),
                )
                .outerjoin(ChatMessage)
                .where(
                    and_(
                        ChatConversation.user_id == user_id,
                        ChatConversation.created_at >= date_from,
                    )
                )
                .group_by(func.date(ChatConversation.created_at))
                .order_by("date")
            )
            daily_results = daily_activity.all()

            # Handle case where conv_result might be None or missing attributes
            total = getattr(conv_result, "total", 0) or 0
            unique_providers = getattr(conv_result, "unique_providers", 0) or 0
            avg_messages = getattr(conv_result, "avg_messages", 0) or 0
            total_messages = getattr(conv_result, "total_messages", 0) or 0

            return {
                "period_days": days,
                "conversation_stats": {
                    "total": total,
                    "unique_providers": unique_providers,
                    "average_messages": float(avg_messages),
                    "total_messages": total_messages,
                },
                "message_stats": [
                    {
                        "role": result.role,
                        "count": result.count,
                        "average_tokens": float(result.avg_tokens or 0),
                    }
                    for result in message_results
                ],
                "provider_usage": [
                    {
                        "provider_id": result.provider_id,
                        "conversation_count": result.conversation_count,
                        "message_count": result.message_count or 0,
                    }
                    for result in provider_results
                ],
                "daily_activity": [
                    {
                        "date": result.date.isoformat(),
                        "conversations": result.conversations,
                        "messages": result.messages or 0,
                    }
                    for result in daily_results
                ],
            }

        except Exception as e:
            logger.error(f"Failed to get user conversation stats: {e}")
            raise

    async def get_message_attachments(
        self, conversation_id: str, user_id: str, mime_type_filter: Optional[str] = None
    ) -> List[MessageAttachment]:
        """Get attachments for a conversation."""
        try:
            # Verify conversation ownership
            conv_result = await self.db_session.execute(
                select(ChatConversation.id).where(
                    and_(
                        ChatConversation.id == conversation_id,
                        ChatConversation.user_id == user_id,
                    )
                )
            )
            if not conv_result.scalar_one_or_none():
                return []

            # Build query
            query = (
                select(MessageAttachment)
                .join(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
            )

            if mime_type_filter:
                query = query.where(
                    MessageAttachment.mime_type.like(f"%{mime_type_filter}%")
                )

            query = query.order_by(desc(MessageAttachment.created_at))

            result = await self.db_session.execute(query)
            return list(result.scalars().all())

        except Exception as e:
            logger.error(f"Failed to get message attachments: {e}")
            raise

    async def bulk_delete_messages(
        self, conversation_id: str, user_id: str, message_ids: List[str]
    ) -> int:
        """Bulk delete messages from a conversation."""
        try:
            # Verify conversation ownership
            conv_result = await self.db_session.execute(
                select(ChatConversation.id).where(
                    and_(
                        ChatConversation.id == conversation_id,
                        ChatConversation.user_id == user_id,
                    )
                )
            )
            if not conv_result.scalar_one_or_none():
                return 0

            # Delete messages
            delete_result = await self.db_session.execute(
                delete(ChatMessage).where(
                    and_(
                        ChatMessage.conversation_id == conversation_id,
                        ChatMessage.id.in_(message_ids),
                    )
                )
            )

            deleted_count = getattr(delete_result, "rowcount", 0) or 0

            # Update conversation message count
            await self.db_session.execute(
                update(ChatConversation)
                .where(ChatConversation.id == conversation_id)
                .values(
                    message_count=func.coalesce(
                        select(func.count(ChatMessage.id)).where(
                            ChatMessage.conversation_id == conversation_id
                        ),
                        0,
                    )
                )
            )

            await self.db_session.commit()
            return deleted_count

        except Exception as e:
            await self.db_session.rollback()
            logger.error(f"Failed to bulk delete messages: {e}")
            raise

    async def get_conversation_export_data(
        self,
        user_id: str,
        conversation_ids: Optional[List[str]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        include_archived: bool = False,
    ) -> List[ChatConversation]:
        """Get conversation data for export."""
        try:
            # Build query
            query = select(ChatConversation).where(ChatConversation.user_id == user_id)

            if conversation_ids:
                query = query.where(ChatConversation.id.in_(conversation_ids))

            if date_from:
                query = query.where(ChatConversation.created_at >= date_from)

            if date_to:
                query = query.where(ChatConversation.created_at <= date_to)

            if not include_archived:
                query = query.where(ChatConversation.is_archived == False)

            # Include all related data
            query = query.options(
                selectinload(ChatConversation.messages).joinedload(
                    ChatMessage.attachments
                ),
                selectinload(ChatConversation.sessions),
            ).order_by(desc(ChatConversation.updated_at))

            result = await self.db_session.execute(query)
            return list(result.scalars().all())

        except Exception as e:
            logger.error(f"Failed to get conversation export data: {e}")
            raise

    async def optimize_database_indexes(self) -> Dict[str, Any]:
        """Optimize database indexes for better performance."""
        try:
            # This would typically be run by a database administrator
            # Here we'll just return information about what should be optimized

            optimization_suggestions = [
                {
                    "table": "chat_conversations",
                    "suggested_indexes": [
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_conversations_user_updated ON chat_conversations(user_id, updated_at DESC);",
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_conversations_metadata_gin ON chat_conversations USING GIN(metadata);",
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_conversations_provider_created ON chat_conversations(provider_id, created_at);",
                    ],
                },
                {
                    "table": "chat_messages",
                    "suggested_indexes": [
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_messages_conversation_created ON chat_messages(conversation_id, created_at ASC);",
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_messages_content_gin ON chat_messages USING GIN(to_tsvector('english', content));",
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_messages_parent_message ON chat_messages(parent_message_id);",
                    ],
                },
                {
                    "table": "message_attachments",
                    "suggested_indexes": [
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_attachments_message_created ON message_attachments(message_id, created_at);",
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_attachments_mime_type ON message_attachments(mime_type);",
                    ],
                },
            ]

            return {
                "optimization_suggestions": optimization_suggestions,
                "note": "These indexes should be created during maintenance windows",
                "performance_impact": "High - significantly improves query performance",
            }

        except Exception as e:
            logger.error(f"Failed to generate database optimization suggestions: {e}")
            raise


async def get_db_session():
    """Dependency generator for getting async database session."""
    from ..database_config import get_database_manager
    manager = get_database_manager()
    async with manager.session() as session:
        yield session
