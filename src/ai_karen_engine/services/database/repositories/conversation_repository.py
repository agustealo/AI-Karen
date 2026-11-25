"""Conversation repository contract for KAREN's durable conversation layer."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from ai_karen_engine.persistence.repositories.chat_run_repository import ChatRunLease
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext

from .base import Repository, RepositoryResult


@dataclass
class Conversation:
    """Canonical conversation representation."""

    id: str
    tenant_id: str
    user_id: str
    session_id: Optional[str] = None
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


def canonical_message_digest(message: Message) -> str:
    """Digest exactly the saved canonical assistant message, not its UI projection.

    The payload is stable across JSONB round trips and binds the id, conversation
    owner scope, role, text and ALL metadata, including evidence provenance.
    """
    payload = {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "tenant_id": message.tenant_id,
        "role": message.role,
        "content": message.content,
        "metadata": message.metadata,
    }
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_draft_attachment_references(value: object) -> list[dict[str, str]]:
    """Validate a bounded, ordered set of canonical metadata references."""
    if not isinstance(value, list) or len(value) > 12:
        raise ValueError("composer_attachment_invalid")
    seen: set[str] = set()
    references: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"source_id", "revision"}:
            raise ValueError("composer_attachment_invalid")
        source_id, revision = item["source_id"], item["revision"]
        if (
            not isinstance(source_id, str)
            or not isinstance(revision, str)
            or not re.fullmatch(r"[a-f0-9]{64}", revision)
        ):
            raise ValueError("composer_attachment_invalid")
        try:
            canonical_id = str(uuid.UUID(source_id))
        except ValueError:
            raise ValueError("composer_attachment_invalid") from None
        if source_id != canonical_id or source_id in seen:
            raise ValueError("composer_attachment_invalid")
        seen.add(source_id)
        references.append({"source_id": source_id, "revision": revision})
    return references


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
    async def get_conversation_by_session(
        self,
        session_id: str,
        tenant_id: str,
        user_id: str,
    ) -> RepositoryResult[Optional[Conversation]]:
        """Retrieve one tenant/user-owned conversation by runtime session id."""

    @abstractmethod
    async def count_conversations(
        self,
        query: ConversationQuery,
    ) -> RepositoryResult[int]:
        """Count conversations matching the same tenant/user filters as list."""

    @abstractmethod
    async def update_conversation(self, conversation: Conversation) -> RepositoryResult[bool]:
        """Update conversation metadata, title, tags, etc."""

    @abstractmethod
    async def delete_conversation(
        self, conversation_id: str, tenant_id: str, *, user_id: str
    ) -> RepositoryResult[bool]:
        """Delete a conversation and its messages."""

    async def get_composer_draft(
        self, conversation_id: str, tenant_id: str, *, user_id: str
    ) -> RepositoryResult[Dict[str, Any]]:
        """Read one owned unsent draft. Missing implementations fail closed."""
        return RepositoryResult(success=False, error="composer_draft_not_supported")

    async def put_composer_draft(
        self, conversation_id: str, tenant_id: str, *, user_id: str,
        content: str, expected_revision: int,
    ) -> RepositoryResult[Dict[str, Any]]:
        """Atomically CAS one owned draft; never append it to the transcript."""
        return RepositoryResult(success=False, error="composer_draft_not_supported")

    async def get_composer_draft_with_attachments(
        self, conversation_id: str, tenant_id: str, *, user_id: str,
    ) -> RepositoryResult[Dict[str, Any]]:
        """Read owned draft references, without conferring content access."""
        return RepositoryResult(success=False, error="composer_attachment_not_supported")

    async def put_composer_draft_with_attachments(
        self, conversation_id: str, tenant_id: str, *, user_id: str,
        content: str, expected_revision: int,
        attachment_references: list[dict[str, str]],
    ) -> RepositoryResult[Dict[str, Any]]:
        """Atomically replace text and references; unsupported stores deny."""
        return RepositoryResult(success=False, error="composer_attachment_not_supported")

    @abstractmethod
    async def add_message(self, message: Message) -> RepositoryResult[str]:
        """Append a message to a conversation."""

    async def add_completed_turn(
        self, user_message: Message, assistant_message: Message,
        *, run_lease: Optional["ChatRunLease"] = None,
        private_execution: Optional["ChatExecutionContext"] = None,
    ) -> RepositoryResult[int]:
        """Atomically persist a pair; unsupported repositories fail closed."""
        return RepositoryResult(
            success=False, error="atomic_completed_turn_not_supported"
        )

    async def read_committed_turn(
        self,
        *,
        conversation_id: str,
        tenant_id: str,
        user_id: str,
        request_id: str,
        correlation_id: str,
        session_id: Optional[str],
        user_message_id: str,
        assistant_message_id: str,
        user_text: str,
        assistant_text: str,
        persona_scope_id: Optional[str] = None,
        private_execution: Optional["ChatExecutionContext"] = None,
        run_lease: Optional["ChatRunLease"] = None,
    ) -> RepositoryResult[bool]:
        """Verify an exact committed pair after an interrupted write.

        This is a scoped read-only reconciliation contract, not a second writer.
        For a leased run the same transaction must also verify the exact
        run-ledger message IDs and canonical assistant digest.
        Unsupported stores must not fabricate a negative or positive receipt.
        """
        return RepositoryResult(success=False, error="committed_turn_read_not_supported")

    @abstractmethod
    async def get_messages(
        self, conversation_id: str, tenant_id: str, limit: int = 100, offset: int = 0,
        *, newest_first: bool = False,
    ) -> RepositoryResult[List[Message]]:
        """Read canonical messages in a bounded deterministic order.

        Normal reads remain chronological. Only an explicit, owner-governed
        recent-window read may request reverse chronological order. Consumers
        must reverse that result for the visible canonical conversation.
        """

    @abstractmethod
    async def update_message(self, message: Message) -> RepositoryResult[bool]:
        """Update an existing message."""

    @abstractmethod
    async def delete_message(self, message_id: str, tenant_id: str) -> RepositoryResult[bool]:
        """Delete a message."""
