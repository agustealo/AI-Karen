"""Conversation repository contract for KAREN's durable conversation layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from .base import Repository, RepositoryResult


@dataclass
class Conversation:
    """Canonical conversation representation."""

    id: str
    tenant_id: str
    user_id: str
    title: Optional[str] = None
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    summary: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    """Canonical message representation."""

    id: str
    conversation_id: str
    tenant_id: str
    role: str
    content: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    parent_message_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationQuery:
    """Query parameters for conversations."""

    tenant_id: str
    user_id: Optional[str] = None
    is_active: Optional[bool] = None
    tags: List[str] = field(default_factory=list)
    created_after: Optional[datetime] = None
    limit: int = 50
    offset: int = 0


class ConversationRepository(Repository):
    """Canonical contract for durable conversation persistence.

    All conversation, message, and revision state flows through this
    repository.  Duplicate stores (chat_conversations, conversations)
    are converged behind this interface.
    """

    @abstractmethod
    async def create_conversation(self, conversation: Conversation) -> RepositoryResult[str]:
        """Create a conversation. Returns the assigned id."""

    @abstractmethod
    async def get_conversation(self, conversation_id: str, tenant_id: str) -> RepositoryResult[Optional[Conversation]]:
        """Retrieve a conversation by id."""

    @abstractmethod
    async def list_conversations(self, query: ConversationQuery) -> RepositoryResult[Sequence[Conversation]]:
        """List conversations matching query filters."""

    @abstractmethod
    async def update_conversation(self, conversation: Conversation) -> RepositoryResult[bool]:
        """Update conversation metadata, title, tags, etc."""

    @abstractmethod
    async def delete_conversation(self, conversation_id: str, tenant_id: str) -> RepositoryResult[bool]:
        """Delete a conversation and its messages."""

    @abstractmethod
    async def add_message(self, message: Message) -> RepositoryResult[str]:
        """Append a message to a conversation."""

    @abstractmethod
    async def get_messages(
        self, conversation_id: str, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> RepositoryResult[List[Message]]:
        """Retrieve messages for a conversation in chronological order."""

    @abstractmethod
    async def update_message(self, message: Message) -> RepositoryResult[bool]:
        """Update an existing message."""

    @abstractmethod
    async def delete_message(self, message_id: str, tenant_id: str) -> RepositoryResult[bool]:
        """Delete a message."""
