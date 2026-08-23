"""
Production-grade conversation management system for AI Karen.
Handles multi-tenant conversations with advanced features like context management,
conversation summarization, and intelligent memory integration.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import delete, func, select, update

from ai_karen_engine.core.model_runtime.embedding_manager import EmbeddingManager
from ai_karen_engine.database.client import MultiTenantPostgresClient
from ai_karen_engine.database.id_types import coerce_user_id
from ai_karen_engine.database.memory_manager import MemoryManager, MemoryQuery
from ai_karen_engine.database.models import TenantConversation, TenantMessage
from ai_karen_engine.models.usage_service import UsageService

logger = logging.getLogger(__name__)


class MessageRole(Enum):
    """Message roles in conversation."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    FUNCTION = "function"


@dataclass
class Message:
    """Represents a conversation message."""

    id: str
    role: MessageRole
    content: str
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    function_call: Optional[Dict[str, Any]] = None
    function_response: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
            "function_call": self.function_call,
            "function_response": self.function_response,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            role=MessageRole(data["role"]),
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            metadata=data.get("metadata", {}),
            function_call=data.get("function_call"),
            function_response=data.get("function_response"),
        )


@dataclass
class Conversation:
    """Represents a complete conversation."""

    id: str
    user_id: str
    title: Optional[str]
    messages: List[Message]
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "messages": [msg.to_dict() for msg in self.messages],
            "metadata": self.metadata,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "message_count": len(self.messages),
            "last_message_at": self.messages[-1].timestamp.isoformat()
            if self.messages
            else None,
        }

    def get_context_window(self, max_messages: int = 20) -> List[Message]:
        """Get recent messages for context window."""
        return self.messages[-max_messages:] if self.messages else []

    def get_summary_text(self) -> str:
        """Get a text summary of the conversation."""
        if not self.messages:
            return "Empty conversation"

        user_messages = [m for m in self.messages if m.role == MessageRole.USER]
        assistant_messages = [
            m for m in self.messages if m.role == MessageRole.ASSISTANT
        ]

        summary_parts = []
        if self.title:
            summary_parts.append(f"Title: {self.title}")

        summary_parts.append(f"Messages: {len(self.messages)}")
        summary_parts.append(f"User messages: {len(user_messages)}")
        summary_parts.append(f"Assistant messages: {len(assistant_messages)}")

        if self.messages:
            summary_parts.append(f"Started: {self.messages[0].timestamp}")
            summary_parts.append(f"Last activity: {self.messages[-1].timestamp}")

        return " | ".join(summary_parts)


class ConversationManager:
    """Production-grade conversation management system."""

    def __init__(
        self,
        db_client: MultiTenantPostgresClient,
        memory_manager: Optional[MemoryManager] = None,
        embedding_manager: Optional[EmbeddingManager] = None,
        conversation_repository: Optional[Any] = None,
    ):
        """Initialize conversation manager.

        Args:
            db_client: Database client
            memory_manager: Memory manager for context integration
            embedding_manager: Embedding manager for conversation analysis
            conversation_repository: Canonical ConversationRepository (preferred)
        """
        self.db_client = db_client
        self.memory_manager = memory_manager
        self.embedding_manager = embedding_manager
        self.conversation_repository = conversation_repository

        # Configuration
        self.max_context_messages = 50
        self.auto_title_threshold = 3  # Auto-generate title after N messages
        self.summary_interval_messages = 100  # Summarize every N messages
        self.inactive_threshold_days = 30  # Mark as inactive after N days

        # Performance tracking
        self.metrics = {
            "conversations_created": 0,
            "messages_added": 0,
            "conversations_retrieved": 0,
            "summaries_generated": 0,
            "avg_response_time": 0.0,
        }

    @staticmethod
    def _payload_value(payload: Any, *names: str, default: Any = None) -> Any:
        """Read a value from either a dict-like payload or an object."""
        for name in names:
            if isinstance(payload, dict) and name in payload:
                value = payload.get(name)
            else:
                value = getattr(payload, name, None)
            if value is not None:
                return value
        return default

    async def create_conversation(
        self,
        tenant_id: Union[str, uuid.UUID],
        user_id: str,
        title: Optional[str] = None,
        initial_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Conversation:
        """Create a new conversation.

        Args:
            tenant_id: Tenant ID
            user_id: User ID
            title: Conversation title
            initial_message: Initial user message
            metadata: Additional metadata

        Returns:
            Created conversation
        """
        start_time = time.time()

        try:
            conversation_id = str(uuid.uuid4())
            messages: List[Message] = []

            # Canonical repository path
            if self.conversation_repository is not None:
                from ai_karen_engine.services.database.repositories import Conversation as CanonicalConversation
                conversation = CanonicalConversation(
                    id=conversation_id,
                    tenant_id=str(tenant_id),
                    user_id=user_id,
                    title=title,
                    metadata=metadata or {},
                )
                result = await self.conversation_repository.create_conversation(conversation)
                if not result.success:
                    raise RuntimeError(f"Failed to create conversation: {result.error}")

                if initial_message:
                    from ai_karen_engine.services.database.repositories import Message as CanonicalMessage
                    message = CanonicalMessage(
                        id=str(uuid.uuid4()),
                        conversation_id=conversation_id,
                        tenant_id=str(tenant_id),
                        role="user",
                        content=initial_message,
                    )
                    msg_result = await self.conversation_repository.add_message(message)
                    if msg_result.success:
                        messages.append(
                            Message(
                                id=message.id,
                                role=MessageRole.USER,
                                content=initial_message,
                                timestamp=datetime.utcnow(),
                            )
                        )

                self.metrics["conversations_created"] += 1
                response_time = time.time() - start_time
                self.metrics["avg_response_time"] = (
                    self.metrics["avg_response_time"] * 0.9 + response_time * 0.1
                )
                logger.info(f"Created conversation {conversation_id} for user {user_id} (canonical)")
                return Conversation(
                    id=conversation_id,
                    user_id=user_id,
                    title=title,
                    messages=messages,
                    metadata=metadata or {},
                    is_active=True,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )

            # Legacy path
            conversation = Conversation(
                id=conversation_id,
                user_id=user_id,
                title=title,
                messages=messages,
                metadata=metadata or {},
            )

            # Store in database
            normalized_user_id = coerce_user_id(user_id)

            async with self.db_client.get_async_session() as session:
                db_conversation = TenantConversation(
                    id=uuid.UUID(conversation_id),
                    user_id=normalized_user_id,
                    title=title,
                    conversation_metadata=metadata or {},
                )

                session.add(db_conversation)
                try:
                    await session.flush()
                except Exception as flush_exc:
                    logger.exception(
                        f"❌ Database flush failed during conversation creation: {flush_exc}"
                    )
                    raise

                # Add initial message if provided
                if initial_message:
                    message = Message(
                        id=str(uuid.uuid4()),
                        role=MessageRole.USER,
                        content=initial_message,
                        timestamp=datetime.utcnow(),
                    )
                    messages.append(message)

                    db_message = TenantMessage(
                        id=uuid.UUID(message.id),
                        conversation_id=db_conversation.id,
                        role=message.role.value,
                        content=message.content,
                        message_metadata=message.metadata,
                        function_call=message.function_call,
                        function_response=message.function_response,
                        created_at=message.timestamp,
                    )
                    session.add(db_message)

                await session.commit()

            # Store initial message in memory if available
            if initial_message and self.memory_manager:
                await self.memory_manager.store_memory(
                    tenant_id=tenant_id,
                    content=initial_message,
                    scope=f"user:{user_id}",
                    kind="conversation_start",
                    metadata={
                        "type": "conversation_start",
                        "conversation_id": conversation_id,
                        "user_id": user_id,
                        "session_id": conversation_id,
                    },
                )

            self.metrics["conversations_created"] += 1

            response_time = time.time() - start_time
            self.metrics["avg_response_time"] = (
                self.metrics["avg_response_time"] * 0.9 + response_time * 0.1
            )

            logger.info(f"Created conversation {conversation_id} for user {user_id}")
            return conversation

        except Exception as e:
            logger.error(f"Failed to create conversation: {e}")
            raise

    async def ensure_conversation(
        self,
        tenant_id: Union[str, uuid.UUID],
        user_id: str,
        conversation_id: str,
        *,
        title: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Conversation:
        """Ensure a durable conversation record exists for the supplied identifier."""
        normalized_user_id = coerce_user_id(user_id)
        conversation_uuid = uuid.UUID(str(conversation_id))
        conversation_metadata = metadata or {}

        async with self.db_client.get_async_session() as session:
            result = await session.execute(
                select(TenantConversation).where(
                    TenantConversation.id == conversation_uuid
                )
            )
            db_conversation = result.scalar_one_or_none()

            if db_conversation is None:
                db_conversation = TenantConversation(
                    id=conversation_uuid,
                    user_id=normalized_user_id,
                    title=title,
                    conversation_metadata=conversation_metadata,
                    session_id=session_id or conversation_id,
                )
                session.add(db_conversation)
                await session.commit()
                return Conversation(
                    id=str(db_conversation.id),
                    user_id=user_id,
                    title=db_conversation.title,
                    messages=[],
                    metadata=db_conversation.conversation_metadata or {},
                    is_active=db_conversation.is_active,
                    created_at=db_conversation.created_at,
                    updated_at=db_conversation.updated_at,
                )

            updates: Dict[str, Any] = {"updated_at": datetime.utcnow()}
            if session_id and db_conversation.session_id != session_id:
                updates["session_id"] = session_id
            if title and not db_conversation.title:
                updates["title"] = title
            if conversation_metadata:
                merged_metadata = dict(db_conversation.conversation_metadata or {})
                merged_metadata.update(conversation_metadata)
                updates["conversation_metadata"] = merged_metadata

            if len(updates) > 1:
                await session.execute(
                    update(TenantConversation)
                    .where(TenantConversation.id == conversation_uuid)
                    .values(**updates)
                )
                await session.commit()
                db_conversation = await session.get(
                    TenantConversation, conversation_uuid
                )

            return Conversation(
                id=str(db_conversation.id),
                user_id=user_id,
                title=db_conversation.title,
                messages=[],
                metadata=db_conversation.conversation_metadata or {},
                is_active=db_conversation.is_active,
                created_at=db_conversation.created_at,
                updated_at=db_conversation.updated_at,
            )

    async def create_user_message(self, request: Any) -> Dict[str, Any]:
        """Persist the user turn as the canonical conversation truth."""
        conversation_id = str(
            self._payload_value(request, "conversation_id") or ""
        ).strip()
        if not conversation_id:
            raise ValueError("conversation_id is required to persist a user message")

        user_id = (
            str(self._payload_value(request, "user_id") or "").strip() or "anonymous"
        )
        tenant_id = self._payload_value(
            request, "tenant_id", "org_id", default="default"
        )
        metadata = dict(self._payload_value(request, "metadata", default={}) or {})
        title = (
            str(self._payload_value(request, "message", default="") or "").strip()[:120]
            or None
        )

        await self.ensure_conversation(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            title=title,
            session_id=str(
                self._payload_value(request, "session_id", default=conversation_id)
                or conversation_id
            ),
            metadata={"source": metadata.get("source", "chat_orchestrator")},
        )

        message = await self.add_message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=str(self._payload_value(request, "message") or ""),
            metadata=metadata,
        )
        if message is None:
            raise RuntimeError(
                f"Failed to persist user message for conversation {conversation_id}"
            )

        return {
            "id": message.id,
            "conversation_id": conversation_id,
            "role": message.role.value,
            "content": message.content,
            "created_at": message.timestamp.isoformat(),
            "metadata": message.metadata,
        }

    async def create_assistant_message(
        self, request: Any, response: Any
    ) -> Dict[str, Any]:
        """Persist the assistant turn once after final response finalization."""
        conversation_id = str(
            self._payload_value(request, "conversation_id") or ""
        ).strip()
        if not conversation_id:
            raise ValueError(
                "conversation_id is required to persist an assistant message"
            )

        assistant_content = str(
            self._payload_value(response, "response", default="") or ""
        ).strip()
        if not assistant_content:
            return {}

        user_id = (
            str(self._payload_value(request, "user_id") or "").strip() or "anonymous"
        )
        tenant_id = self._payload_value(
            request, "tenant_id", "org_id", default="default"
        )
        response_metadata = dict(
            self._payload_value(response, "metadata", default={}) or {}
        )
        response_status = self._payload_value(response, "status", default="completed")
        if hasattr(response_status, "value"):
            response_status = response_status.value
        response_metadata.setdefault("status", str(response_status))
        response_metadata.setdefault(
            "execution_path", self._payload_value(response, "execution_path")
        )
        response_metadata.setdefault(
            "used_fallback",
            bool(self._payload_value(response, "used_fallback", default=False)),
        )
        response_metadata.setdefault(
            "request_id", self._payload_value(response, "request_id")
        )
        response_metadata.setdefault(
            "correlation_id", self._payload_value(response, "correlation_id")
        )

        await self.ensure_conversation(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            session_id=str(
                self._payload_value(request, "session_id", default=conversation_id)
                or conversation_id
            ),
            metadata={"last_request_id": self._payload_value(response, "request_id")},
        )

        message = await self.add_message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=assistant_content,
            metadata=response_metadata,
        )
        if message is None:
            raise RuntimeError(
                f"Failed to persist assistant message for conversation {conversation_id}"
            )

        return {
            "id": message.id,
            "conversation_id": conversation_id,
            "role": message.role.value,
            "content": message.content,
            "created_at": message.timestamp.isoformat(),
            "metadata": message.metadata,
        }

    async def load_recent_messages(
        self,
        tenant_id: Union[str, uuid.UUID],
        conversation_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Load recent durable messages in chronological order for working context."""
        conversation_uuid = uuid.UUID(str(conversation_id))
        async with self.db_client.get_async_session() as session:
            result = await session.execute(
                select(TenantMessage)
                .where(TenantMessage.conversation_id == conversation_uuid)
                .order_by(TenantMessage.created_at.desc())
                .limit(limit)
            )
            serialized_messages = [
                {
                    "id": str(message.id),
                    "role": message.role,
                    "content": message.content,
                    "metadata": message.message_metadata or {},
                    "created_at": message.created_at.isoformat(),
                }
                for message in result.scalars().all()
            ]

        serialized_messages.reverse()
        return serialized_messages

    async def get_conversation(
        self,
        tenant_id: Union[str, uuid.UUID],
        conversation_id: str,
        include_context: bool = True,
    ) -> Optional[Conversation]:
        """Get conversation by ID.

        Args:
            tenant_id: Tenant ID
            conversation_id: Conversation ID
            include_context: Whether to include memory context

        Returns:
            Conversation if found
        """
        try:
            # Canonical repository path
            if self.conversation_repository is not None:
                from ai_karen_engine.services.database.repositories import ConversationQuery
                query = ConversationQuery(tenant_id=str(tenant_id), limit=1)
                result = await self.conversation_repository.list_conversations(query)
                if not result.success or not result.data:
                    return None

                canonical_conv = result.data[0]
                messages_result = await self.conversation_repository.get_messages(
                    canonical_conv.id, canonical_conv.tenant_id
                )
                messages = []
                if messages_result.success and messages_result.data:
                    for msg in messages_result.data:
                        messages.append(
                            Message(
                                id=msg.id,
                                role=MessageRole(msg.role),
                                content=msg.content,
                                timestamp=msg.created_at,
                                metadata=msg.metadata,
                            )
                        )

                conversation = Conversation(
                    id=canonical_conv.id,
                    user_id=canonical_conv.user_id,
                    title=canonical_conv.title,
                    messages=messages,
                    metadata=canonical_conv.metadata,
                    is_active=canonical_conv.is_active,
                    created_at=canonical_conv.created_at,
                    updated_at=canonical_conv.updated_at,
                )

                if include_context and self.memory_manager and messages:
                    await self._add_memory_context(tenant_id, conversation)

                self.metrics["conversations_retrieved"] += 1
                return conversation

            # Legacy path
            async with self.db_client.get_async_session() as session:
                result = await session.execute(
                    select(TenantConversation).where(
                        TenantConversation.id == uuid.UUID(conversation_id)
                    )
                )

                db_conversation = result.scalar_one_or_none()
                if not db_conversation:
                    return None

                # Load messages
                msg_result = await session.execute(
                    select(TenantMessage)
                    .where(TenantMessage.conversation_id == db_conversation.id)
                    .order_by(TenantMessage.created_at.asc())
                )
                db_messages = msg_result.scalars().all()

                messages = [
                    Message(
                        id=str(m.id),
                        role=MessageRole(m.role),
                        content=m.content,
                        timestamp=m.created_at,
                        metadata=m.message_metadata or {},
                        function_call=m.function_call,
                        function_response=m.function_response,
                    )
                    for m in db_messages
                ]

                conversation = Conversation(
                    id=str(db_conversation.id),
                    user_id=str(db_conversation.user_id),
                    title=db_conversation.title,
                    messages=messages,
                    metadata=db_conversation.conversation_metadata or {},
                    is_active=db_conversation.is_active,
                    created_at=db_conversation.created_at,
                    updated_at=db_conversation.updated_at,
                )

                # Add memory context if requested
                if include_context and self.memory_manager and messages:
                    await self._add_memory_context(tenant_id, conversation)

                self.metrics["conversations_retrieved"] += 1
                return conversation

        except Exception as e:
            logger.error(f"Failed to get conversation {conversation_id}: {e}")
            return None

    async def add_message(
        self,
        tenant_id: Union[str, uuid.UUID],
        conversation_id: str,
        role: MessageRole,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        function_call: Optional[Dict[str, Any]] = None,
        function_response: Optional[Dict[str, Any]] = None,
    ) -> Optional[Message]:
        """Add a message to conversation.

        Args:
            tenant_id: Tenant ID
            conversation_id: Conversation ID
            role: Message role
            content: Message content
            metadata: Message metadata
            function_call: Function call data
            function_response: Function response data

        Returns:
            Added message
        """
        try:
            # Canonical repository path
            if self.conversation_repository is not None:
                message = Message(
                    id=str(uuid.uuid4()),
                    role=role,
                    content=content,
                    timestamp=datetime.utcnow(),
                    metadata=metadata or {},
                    function_call=function_call,
                    function_response=function_response,
                )
                canonical_msg = CanonicalMessage(
                    id=message.id,
                    conversation_id=conversation_id,
                    tenant_id=str(tenant_id),
                    role=message.role.value,
                    content=message.content,
                    metadata=message.metadata,
                )
                result = await self.conversation_repository.add_message(canonical_msg)
                if not result.success:
                    logger.error("Failed to add message via canonical repository: %s", result.error)
                    return None
                self.metrics["messages_added"] += 1
                return message

            # Legacy path
            message = Message(
                id=str(uuid.uuid4()),
                role=role,
                content=content,
                timestamp=datetime.utcnow(),
                metadata=metadata or {},
                function_call=function_call,
                function_response=function_response,
            )

            # Update conversation in database
            user_id_for_memory = None
            conversation_title = None
            current_message_count = 0
            async with self.db_client.get_async_session() as session:
                # Get current conversation
                result = await session.execute(
                    select(TenantConversation).where(
                        TenantConversation.id == uuid.UUID(conversation_id)
                    )
                )

                db_conversation = result.scalar_one_or_none()
                if not db_conversation:
                    logger.error(f"Conversation {conversation_id} not found")
                    return None

                # Capture values we need outside the session
                user_id_for_memory = db_conversation.user_id
                conversation_title = db_conversation.title

                db_message = TenantMessage(
                    id=uuid.UUID(message.id),
                    conversation_id=db_conversation.id,
                    role=message.role.value,
                    content=message.content,
                    message_metadata=message.metadata,
                    function_call=message.function_call,
                    function_response=message.function_response,
                    created_at=message.timestamp,
                )
                session.add(db_message)

                await session.execute(
                    update(TenantConversation)
                    .where(TenantConversation.id == db_conversation.id)
                    .values(updated_at=datetime.utcnow())
                )

                await session.flush()

                count_result = await session.execute(
                    select(func.count())
                    .select_from(TenantMessage)
                    .where(TenantMessage.conversation_id == db_conversation.id)
                )
                current_message_count = count_result.scalar()

                await session.commit()

            # Increment usage counter
            UsageService.increment(
                "messages", tenant_id=str(tenant_id), user_id=user_id_for_memory
            )

            # Store in memory if it's a user message
            if role == MessageRole.USER and self.memory_manager and user_id_for_memory:
                await self.memory_manager.store_memory(
                    tenant_id=tenant_id,
                    content=content,
                    scope=f"user:{user_id_for_memory}",
                    kind="user_message",
                    metadata={
                        "type": "user_message",
                        "conversation_id": conversation_id,
                        "message_id": message.id,
                        "user_id": str(user_id_for_memory),
                        "session_id": conversation_id,
                    },
                )

            # Auto-generate title if needed
            if (
                current_message_count == self.auto_title_threshold
                and not conversation_title
            ):
                await self._auto_generate_title(tenant_id, conversation_id)

            # Generate summary if needed
            if current_message_count % self.summary_interval_messages == 0:
                await self._generate_conversation_summary(tenant_id, conversation_id)

            self.metrics["messages_added"] += 1

            logger.debug(f"Added message to conversation {conversation_id}")
            return message

        except Exception as e:
            logger.error(
                f"Failed to add message to conversation {conversation_id}: {e}"
            )
            UsageService.increment(
                "errors", tenant_id=str(tenant_id), user_id=user_id_for_memory
            )
            return None

    async def list_conversations(
        self,
        tenant_id: Union[str, uuid.UUID],
        user_id: str,
        active_only: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Conversation]:
        """List conversations for a user.

        Args:
            tenant_id: Tenant ID
            user_id: User ID
            active_only: Only return active conversations
            limit: Maximum number of conversations
            offset: Number of conversations to skip

        Returns:
            List of conversations
        """
        try:
            normalized_user_id = coerce_user_id(user_id)

            async with self.db_client.get_async_session() as session:
                query = (
                    select(TenantConversation)
                    .where(TenantConversation.user_id == normalized_user_id)
                    .order_by(TenantConversation.updated_at.desc())
                )

                if active_only:
                    query = query.where(TenantConversation.is_active.is_(True))

                query = query.limit(limit).offset(offset)

                result = await session.execute(query)
                db_conversations = result.scalars().all()

                conversations = []
                for db_conv in db_conversations:
                    msg_result = await session.execute(
                        select(TenantMessage)
                        .where(TenantMessage.conversation_id == db_conv.id)
                        .order_by(TenantMessage.created_at.asc())
                    )
                    db_msgs = msg_result.scalars().all()
                    messages = [
                        Message(
                            id=str(m.id),
                            role=MessageRole(m.role),
                            content=m.content,
                            timestamp=m.created_at,
                            metadata=m.message_metadata or {},
                            function_call=m.function_call,
                            function_response=m.function_response,
                        )
                        for m in db_msgs
                    ]

                    conversation = Conversation(
                        id=str(db_conv.id),
                        user_id=str(db_conv.user_id),
                        title=db_conv.title,
                        messages=messages,
                        metadata=db_conv.conversation_metadata or {},
                        is_active=db_conv.is_active,
                        created_at=db_conv.created_at,
                        updated_at=db_conv.updated_at,
                    )
                    conversations.append(conversation)

                return conversations

        except Exception as e:
            logger.error(f"Failed to list conversations for user {user_id}: {e}")
            return []

    async def update_conversation(
        self,
        tenant_id: Union[str, uuid.UUID],
        conversation_id: str,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_active: Optional[bool] = None,
    ) -> bool:
        """Update conversation properties.

        Args:
            tenant_id: Tenant ID
            conversation_id: Conversation ID
            title: New title
            metadata: New metadata
            is_active: Active status

        Returns:
            True if successful
        """
        try:
            # Canonical repository path
            if self.conversation_repository is not None:
                from ai_karen_engine.services.database.repositories import Conversation as CanonicalConversation
                conv = CanonicalConversation(
                    id=conversation_id,
                    tenant_id=str(tenant_id),
                    user_id="",
                    title=title,
                    metadata=metadata or {},
                    is_active=is_active if is_active is not None else True,
                )
                result = await self.conversation_repository.update_conversation(conv)
                if not result.success:
                    logger.error("Failed to update conversation via canonical repository: %s", result.error)
                    return False
                logger.info(f"Updated conversation {conversation_id} (canonical)")
                return True

            # Legacy path
            updates = {"updated_at": datetime.utcnow()}

            if title is not None:
                updates["title"] = title
            if metadata is not None:
                updates["conversation_metadata"] = metadata
            if is_active is not None:
                updates["is_active"] = is_active

            async with self.db_client.get_async_session() as session:
                await session.execute(
                    update(TenantConversation)
                    .where(TenantConversation.id == uuid.UUID(conversation_id))
                    .values(**updates)
                )
                await session.commit()

            logger.info(f"Updated conversation {conversation_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to update conversation {conversation_id}: {e}")
            return False

    async def delete_conversation(
        self, tenant_id: Union[str, uuid.UUID], conversation_id: str
    ) -> bool:
        """Delete a conversation.

        Args:
            tenant_id: Tenant ID
            conversation_id: Conversation ID

        Returns:
            True if successful
        """
        try:
            # Canonical repository path
            if self.conversation_repository is not None:
                result = await self.conversation_repository.delete_conversation(conversation_id, str(tenant_id))
                if not result.success:
                    logger.error("Failed to delete conversation via canonical repository: %s", result.error)
                    return False
                logger.info(f"Deleted conversation {conversation_id} (canonical)")
                return True

            # Legacy path
            async with self.db_client.get_async_session() as session:
                await session.execute(
                    delete(TenantConversation).where(
                        TenantConversation.id == uuid.UUID(conversation_id)
                    )
                )
                await session.commit()

            # Clean up related memories
            if self.memory_manager:
                # This would require implementing a method to delete memories by session_id
                pass

            logger.info(f"Deleted conversation {conversation_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete conversation {conversation_id}: {e}")
            return False

    async def get_conversation_context(
        self,
        tenant_id: Union[str, uuid.UUID],
        conversation_id: str,
        query_text: str,
        max_context_items: int = 5,
    ) -> List[Dict[str, Any]]:
        """Get relevant context for conversation from memory.

        Args:
            tenant_id: Tenant ID
            conversation_id: Conversation ID
            query_text: Text to find context for
            max_context_items: Maximum context items to return

        Returns:
            List of context items
        """
        if not self.memory_manager:
            return []

        try:
            # Get conversation to find user_id
            conversation = await self.get_conversation(
                tenant_id, conversation_id, include_context=False
            )
            if not conversation:
                return []

            # Query memory for relevant context
            memory_query = MemoryQuery(
                text=query_text,
                user_id=conversation.user_id,
                top_k=max_context_items,
                similarity_threshold=0.7,
            )

            memories = await self.memory_manager.query_memories(tenant_id, memory_query)

            # Convert to context format
            context_items = []
            for memory in memories:
                context_items.append(
                    {
                        "content": memory.content,
                        "timestamp": memory.timestamp,
                        "similarity_score": memory.similarity_score,
                        "metadata": memory.metadata,
                        "source": "memory",
                    }
                )

            return context_items

        except Exception as e:
            logger.error(f"Failed to get conversation context: {e}")
            return []

    async def get_conversation_stats(
        self, tenant_id: Union[str, uuid.UUID], user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get conversation statistics.

        Args:
            tenant_id: Tenant ID
            user_id: Optional user ID to filter by

        Returns:
            Conversation statistics
        """
        try:
            async with self.db_client.get_async_session() as session:
                # Base query
                base_query = select(TenantConversation)
                if user_id:
                    normalized_user_id = coerce_user_id(user_id)
                    base_query = base_query.where(
                        TenantConversation.user_id == normalized_user_id
                    )

                # Total conversations
                total_result = await session.execute(
                    select(func.count()).select_from(base_query.subquery())
                )
                total_conversations = total_result.scalar()

                # Active conversations
                active_result = await session.execute(
                    select(func.count()).select_from(
                        base_query.where(
                            TenantConversation.is_active.is_(True)
                        ).subquery()
                    )
                )
                active_conversations = active_result.scalar()

                # Recent conversations (last 7 days)
                recent_cutoff = datetime.utcnow() - timedelta(days=7)
                recent_result = await session.execute(
                    select(func.count()).select_from(
                        base_query.where(
                            TenantConversation.updated_at > recent_cutoff
                        ).subquery()
                    )
                )
                recent_conversations = recent_result.scalar()

                # Average messages per conversation
                msg_query = (
                    select(func.count())
                    .select_from(TenantMessage)
                    .join(
                        TenantConversation,
                        TenantMessage.conversation_id == TenantConversation.id,
                    )
                )
                if user_id:
                    normalized_user_id = coerce_user_id(user_id)
                    msg_query = msg_query.where(
                        TenantConversation.user_id == normalized_user_id
                    )
                total_messages = (await session.execute(msg_query)).scalar()
                avg_messages = (
                    total_messages / total_conversations
                    if total_conversations > 0
                    else 0
                )

                return {
                    "total_conversations": total_conversations,
                    "active_conversations": active_conversations,
                    "recent_conversations_7d": recent_conversations,
                    "total_messages": total_messages,
                    "avg_messages_per_conversation": round(avg_messages, 2),
                    "metrics": self.metrics.copy(),
                }

        except Exception as e:
            logger.error(f"Failed to get conversation stats: {e}")
            return {"error": str(e)}

    async def _add_memory_context(
        self, tenant_id: Union[str, uuid.UUID], conversation: Conversation
    ):
        """Add relevant memory context to conversation."""
        if not self.memory_manager or not conversation.messages:
            return

        try:
            # Get the last user message for context
            last_user_message = None
            for msg in reversed(conversation.messages):
                if msg.role == MessageRole.USER:
                    last_user_message = msg
                    break

            if not last_user_message:
                return

            # Query for relevant memories
            memory_query = MemoryQuery(
                text=last_user_message.content,
                user_id=conversation.user_id,
                top_k=3,
                similarity_threshold=0.75,
            )

            memories = await self.memory_manager.query_memories(tenant_id, memory_query)

            # Add context to conversation metadata
            if memories:
                conversation.metadata["memory_context"] = [
                    {
                        "content": memory.content,
                        "similarity_score": memory.similarity_score,
                        "timestamp": memory.timestamp,
                    }
                    for memory in memories
                ]

        except Exception as e:
            logger.warning(f"Failed to add memory context: {e}")

    async def _auto_generate_title(
        self, tenant_id: Union[str, uuid.UUID], conversation_id: str
    ):
        """Auto-generate conversation title based on content."""
        try:
            conversation = await self.get_conversation(
                tenant_id, conversation_id, include_context=False
            )
            if not conversation or not conversation.messages:
                return

            # Get first few user messages
            user_messages = [
                msg.content
                for msg in conversation.messages[:5]
                if msg.role == MessageRole.USER
            ]

            if not user_messages:
                return

            # Simple title generation (in production, use LLM)
            first_message = user_messages[0]
            title = (
                first_message[:50] + "..." if len(first_message) > 50 else first_message
            )

            # Update conversation title
            await self.update_conversation(tenant_id, conversation_id, title=title)

            logger.info(
                f"Auto-generated title for conversation {conversation_id}: {title}"
            )

        except Exception as e:
            logger.error(f"Failed to auto-generate title: {e}")

    async def _generate_conversation_summary(
        self, tenant_id: Union[str, uuid.UUID], conversation_id: str
    ):
        """Generate conversation summary for long conversations."""
        try:
            conversation = await self.get_conversation(
                tenant_id, conversation_id, include_context=False
            )
            if (
                not conversation
                or len(conversation.messages) < self.summary_interval_messages
            ):
                return

            # Generate summary (in production, use LLM)
            summary = f"Conversation with {len(conversation.messages)} messages"

            # Store summary in metadata
            metadata = conversation.metadata.copy()
            metadata["summary"] = summary
            metadata["summary_generated_at"] = datetime.utcnow().isoformat()

            await self.update_conversation(
                tenant_id, conversation_id, metadata=metadata
            )

            self.metrics["summaries_generated"] += 1
            logger.info(f"Generated summary for conversation {conversation_id}")

        except Exception as e:
            logger.error(f"Failed to generate conversation summary: {e}")

    async def cleanup_inactive_conversations(
        self, tenant_id: Union[str, uuid.UUID], days_inactive: int = None
    ) -> int:
        """Mark old conversations as inactive.

        Args:
            tenant_id: Tenant ID
            days_inactive: Days of inactivity threshold

        Returns:
            Number of conversations marked inactive
        """
        days_inactive = days_inactive or self.inactive_threshold_days
        cutoff_date = datetime.utcnow() - timedelta(days=days_inactive)

        try:
            async with self.db_client.get_async_session() as session:
                result = await session.execute(
                    update(TenantConversation)
                    .where(
                        TenantConversation.updated_at < cutoff_date,
                        TenantConversation.is_active.is_(True),
                    )
                    .values(is_active=False, updated_at=datetime.utcnow())
                )

                await session.commit()
                count = result.rowcount

                logger.info(
                    f"Marked {count} conversations as inactive for tenant {tenant_id}"
                )
                return count

        except Exception as e:
            logger.error(f"Failed to cleanup inactive conversations: {e}")
            return 0
