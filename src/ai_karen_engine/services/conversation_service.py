"""
Conversation service for managing chat conversations with full CRUD operations,
search, filtering, and analytics capabilities.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple, Union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, and_, or_, desc, func, text
from sqlalchemy.orm import selectinload, joinedload

from ..data_models.chat import (
    ChatConversation,
    ChatMessage,
    ChatSession,
    MessageAttachment,
    ChatProviderConfiguration,
)
from ..database import DatabaseOperations
from ..security import log_security_event, ThreatLevel

logger = logging.getLogger(__name__)


class ConversationService:
    """Service for managing chat conversations with advanced features."""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session
        self.db_ops = DatabaseOperations(db_session)

    async def create_conversation(
        self,
        user_id: str,
        title: Optional[str] = None,
        provider_id: Optional[str] = None,
        model_used: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        is_pinned: bool = False,
        client_ip: Optional[str] = None,
    ) -> ChatConversation:
        """Create a new conversation with enhanced features."""
        try:
            conversation_id = str(uuid.uuid4())

            # Create conversation
            conversation = ChatConversation(
                id=conversation_id,
                user_id=user_id,
                title=title or "New Conversation",
                provider_id=provider_id,
                model_used=model_used,
                metadata=metadata or {},
                created_by_ip=client_ip,
            )

            self.db_session.add(conversation)
            await self.db_session.flush()

            # Log security event
            log_security_event(
                event_type="conversation_created",
                user_id=user_id,
                conversation_id=conversation_id,
                client_ip=client_ip,
                metadata={
                    "title": title,
                    "provider_id": provider_id,
                    "model_used": model_used,
                    "tags": tags,
                    "is_pinned": is_pinned,
                },
            )

            logger.info(f"Created conversation {conversation_id} for user {user_id}")

            # Publish realtime event (adapter integration)
            try:
                from ai_karen_engine.services.database.repositories.realtime_accessor import (
                    publish_conversation_event,
                )
                await publish_conversation_event(
                    tenant_id=user_id,
                    conversation_id=conversation_id,
                    event_name="conversation.created",
                    payload={
                        "conversation_id": conversation_id,
                        "user_id": user_id,
                        "title": title,
                        "provider_id": provider_id,
                    },
                )
            except Exception as exc:
                logger.debug("Realtime publish skipped: %s", exc)

            return conversation

        except Exception as e:
            logger.error(f"Error creating conversation: {e}")
            raise

    async def get_conversation(
        self,
        conversation_id: str,
        user_id: str,
        include_messages: bool = False,
        include_sessions: bool = False,
        include_attachments: bool = False,
    ) -> Optional[ChatConversation]:
        """Get a conversation by ID with optional related data."""
        try:
            query = select(ChatConversation).where(
                ChatConversation.id == conversation_id
            )

            if include_messages:
                query = query.options(selectinload(ChatConversation.messages))
            if include_sessions:
                query = query.options(selectinload(ChatConversation.sessions))
            if include_attachments:
                query = query.options(
                    selectinload(ChatConversation.messages).selectinload(
                        ChatMessage.attachments
                    )
                )

            result = await self.db_session.execute(query)
            conversation = result.scalar_one_or_none()

            if conversation and conversation.user_id == str(user_id):
                # Log access
                await self._log_conversation_access(conversation.id, user_id)
                return conversation
            else:
                logger.warning(
                    f"Conversation {conversation_id} not found or access denied"
                )
                return None

        except Exception as e:
            logger.error(f"Error getting conversation {conversation_id}: {e}")
            raise

    async def update_conversation(
        self,
        conversation_id: str,
        user_id: str,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_archived: Optional[bool] = None,
        is_pinned: Optional[bool] = None,
        client_ip: Optional[str] = None,
    ) -> Optional[ChatConversation]:
        """Update a conversation with security logging."""
        try:
            # Check ownership first
            conversation = await self.get_conversation(conversation_id, user_id)
            if not conversation:
                return None

            # Build update query
            update_data = {}
            if title is not None:
                update_data["title"] = title
            if metadata is not None:
                update_data["metadata"] = metadata
            if is_archived is not None:
                update_data["is_archived"] = is_archived
            if is_pinned is not None:
                update_data["is_pinned"] = is_pinned
            update_data["updated_at"] = datetime.utcnow()
            update_data["last_modified_by"] = f"user:{user_id}"

            # Update conversation
            query = (
                update(ChatConversation)
                .where(ChatConversation.id == conversation_id)
                .values(**update_data)
            )

            await self.db_session.execute(query)
            await self.db_session.flush()

            # Get updated conversation
            updated_conversation = await self.get_conversation(conversation_id, user_id)

            # Log security event
            log_security_event(
                event_type="conversation_updated",
                user_id=user_id,
                conversation_id=conversation_id,
                client_ip=client_ip,
                metadata=update_data,
            )

            logger.info(f"Updated conversation {conversation_id} for user {user_id}")
            return updated_conversation

        except Exception as e:
            logger.error(f"Error updating conversation {conversation_id}: {e}")
            raise

    async def delete_conversation(
        self,
        conversation_id: str,
        user_id: str,
        client_ip: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> bool:
        """Delete a conversation with security logging."""
        try:
            # Check ownership first
            conversation = await self.get_conversation(conversation_id, user_id)
            if not conversation:
                return False

            # Log security event before deletion
            log_security_event(
                event_type="conversation_deleted",
                user_id=user_id,
                conversation_id=conversation_id,
                client_ip=client_ip,
                metadata={"reason": reason or "user_request"},
            )

            # Delete conversation (cascade will handle related records)
            query = delete(ChatConversation).where(
                ChatConversation.id == conversation_id
            )
            result = await self.db_session.execute(query)
            await self.db_session.flush()

            logger.info(f"Deleted conversation {conversation_id} for user {user_id}")
            return result.rowcount > 0

        except Exception as e:
            logger.error(f"Error deleting conversation {conversation_id}: {e}")
            raise

    async def list_conversations(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        include_archived: bool = False,
        include_pinned: bool = False,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        search_term: Optional[str] = None,
        tags: Optional[List[str]] = None,
        provider_id: Optional[str] = None,
        date_range: Optional[Tuple[datetime, datetime]] = None,
    ) -> List[ChatConversation]:
        """List conversations with advanced filtering and sorting."""
        try:
            query = select(ChatConversation).where(
                ChatConversation.user_id == str(user_id)
            )

            # Apply filters
            if not include_archived:
                query = query.where(ChatConversation.is_archived == False)

            if include_pinned:
                query = query.where(
                    ChatConversation.metadata.op("->>")("is_pinned") == "true"
                )

            if search_term:
                search_condition = or_(
                    ChatConversation.title.ilike(f"%{search_term}%"),
                    ChatConversation.metadata.op("->>")("description").ilike(
                        f"%{search_term}%"
                    ),
                )
                query = query.where(search_condition)

            if tags:
                for tag in tags:
                    query = query.where(
                        ChatConversation.metadata.op("->>")("tags").op("?", tag)
                    )

            if provider_id:
                query = query.where(ChatConversation.provider_id == provider_id)

            if date_range:
                start_date, end_date = date_range
                query = query.where(
                    and_(
                        ChatConversation.created_at >= start_date,
                        ChatConversation.created_at <= end_date,
                    )
                )

            # Apply sorting
            if sort_by == "updated_at":
                sort_column = ChatConversation.updated_at
            elif sort_by == "created_at":
                sort_column = ChatConversation.created_at
            elif sort_by == "title":
                sort_column = ChatConversation.title
            elif sort_by == "message_count":
                sort_column = ChatConversation.message_count
            else:
                sort_column = ChatConversation.updated_at

            if sort_order == "desc":
                query = query.order_by(desc(sort_column))
            else:
                query = query.order_by(sort_column)

            # Apply pagination
            query = query.offset(offset).limit(limit)

            result = await self.db_session.execute(query)
            conversations = result.scalars().all()

            logger.info(f"Listed {len(conversations)} conversations for user {user_id}")
            return conversations

        except Exception as e:
            logger.error(f"Error listing conversations for user {user_id}: {e}")
            raise

    async def get_conversation_stats(
        self, user_id: str, conversation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get conversation statistics."""
        try:
            base_query = select(ChatConversation).where(
                ChatConversation.user_id == str(user_id)
            )

            if conversation_id:
                base_query = base_query.where(ChatConversation.id == conversation_id)

            # Count total conversations
            count_query = select(func.count()).select_from(base_query.subquery())
            result = await self.db_session.execute(count_query)
            total_conversations = result.scalar()

            # Get message counts
            if conversation_id:
                # Get stats for specific conversation
                msg_query = select(func.count(ChatMessage.id)).where(
                    ChatMessage.conversation_id == conversation_id
                )
                result = await self.db_session.execute(msg_query)
                message_count = result.scalar() or 0

                # Get latest activity
                activity_query = (
                    select(ChatMessage.created_at)
                    .where(ChatMessage.conversation_id == conversation_id)
                    .order_by(desc(ChatMessage.created_at))
                    .limit(1)
                )
                result = await self.db_session.execute(activity_query)
                last_activity = result.scalar_one_or_none()

                return {
                    "total_conversations": 1,
                    "message_count": message_count,
                    "last_activity": last_activity,
                    "conversation_id": conversation_id,
                }
            else:
                # Get aggregated stats for all conversations
                stats_query = select(
                    func.count(ChatConversation.id).label("total_conversations"),
                    func.sum(ChatConversation.message_count).label("total_messages"),
                    func.max(ChatConversation.updated_at).label("last_activity"),
                    func.count(ChatConversation.id)
                    .filter(ChatConversation.is_archived == False)
                    .label("active_conversations"),
                    func.count(ChatConversation.id)
                    .filter(ChatConversation.metadata.op("->>")("is_pinned") == "true")
                    .label("pinned_conversations"),
                ).where(ChatConversation.user_id == str(user_id))

                result = await self.db_session.execute(stats_query)
                stats = result.fetchone()

                return {
                    "total_conversations": stats.total_conversations,
                    "total_messages": stats.total_messages or 0,
                    "last_activity": stats.last_activity,
                    "active_conversations": stats.active_conversations,
                    "pinned_conversations": stats.pinned_conversations,
                }

        except Exception as e:
            logger.error(f"Error getting conversation stats for user {user_id}: {e}")
            raise

    async def _log_conversation_access(
        self, conversation_id: str, user_id: str, client_ip: Optional[str] = None
    ) -> None:
        """Log conversation access for security monitoring."""
        try:
            # Update access count and timestamp
            update_query = (
                update(ChatConversation)
                .where(ChatConversation.id == conversation_id)
                .values(
                    access_count=ChatConversation.access_count + 1,
                    last_accessed_at=datetime.utcnow(),
                )
            )

            await self.db_session.execute(update_query)

            # Log security event
            log_security_event(
                event_type="conversation_accessed",
                user_id=user_id,
                conversation_id=conversation_id,
                client_ip=client_ip,
                metadata={"action": "view"},
            )

        except Exception as e:
            logger.error(f"Error logging conversation access: {e}")
            # Don't raise this as it's not critical

    async def archive_conversations(
        self, user_id: str, conversation_ids: List[str], client_ip: Optional[str] = None
    ) -> int:
        """Archive multiple conversations."""
        try:
            # Verify ownership of all conversations
            owned_conversations = await self.list_conversations(
                user_id=user_id,
                limit=len(conversation_ids),
                offset=0,
                include_archived=True,
            )

            owned_ids = {conv.id for conv in owned_conversations}
            valid_ids = [cid for cid in conversation_ids if cid in owned_ids]

            if len(valid_ids) != len(conversation_ids):
                invalid_ids = set(conversation_ids) - owned_ids
                logger.warning(
                    f"User {user_id} attempted to archive non-owned conversations: {invalid_ids}"
                )

            # Archive conversations
            update_query = (
                update(ChatConversation)
                .where(ChatConversation.id.in_(valid_ids))
                .values(is_archived=True, updated_at=datetime.utcnow())
            )

            result = await self.db_session.execute(update_query)
            await self.db_session.flush()

            # Log security event
            log_security_event(
                event_type="conversations_archived",
                user_id=user_id,
                conversation_id=valid_ids[0] if valid_ids else None,
                client_ip=client_ip,
                metadata={
                    "archived_count": len(valid_ids),
                    "conversation_ids": valid_ids,
                },
            )

            logger.info(f"Archived {len(valid_ids)} conversations for user {user_id}")
            return len(valid_ids)

        except Exception as e:
            logger.error(f"Error archiving conversations: {e}")
            raise
