"""Runtime adapter for canonical durable conversation persistence.

This module does not own conversation storage. It adapts ChatRuntime execution
identity to the canonical ConversationRepository so runtime code never calls the
legacy Web UI service's memory-coupled message helpers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.persistence.postgres import get_postgres_engine
from ai_karen_engine.services.database.repositories import (
    Conversation,
    ConversationRepository,
    Message,
    RepositoryFactory,
)
from ai_karen_engine.utils.chat_helpers import normalize_session_id

logger = get_logger(__name__)


def resolve_runtime_conversation_id(context: ChatExecutionContext) -> str:
    """Return the canonical durable conversation identity for one runtime request.

    Explicit conversation IDs are authoritative. When ingress supplies only a
    session identity, derive a UUIDv5 from tenant + normalized session so equal
    session strings in separate tenants cannot collide on the globally unique
    ``conversations.conversation_id`` primary key.
    """
    explicit = str(context.conversation_id or "").strip()
    if explicit:
        return explicit

    tenant_id = str(context.tenant_id or "").strip()
    session_id = str(context.session_id or "").strip()
    if not tenant_id:
        raise ValueError("conversation_identity_incomplete:tenant_id")
    if not session_id:
        raise ValueError("conversation_identity_incomplete:session_id")

    normalized_session_id = normalize_session_id(session_id)
    identity = ":".join(
        (
            "ai-karen",
            "conversation",
            tenant_id,
            normalized_session_id,
        )
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, identity))


@dataclass(frozen=True)
class ConversationSnapshot:
    """Tenant/user-authorized canonical conversation plus durable messages."""

    conversation: Conversation
    messages: tuple[Message, ...] = ()


@dataclass(frozen=True)
class TranscriptPersistenceResult:
    """Truthful result of one durable transcript operation."""

    status: str
    conversation_id: str
    user_message_id: Optional[str] = None
    assistant_message_id: Optional[str] = None
    persisted_messages: int = 0
    reason: Optional[str] = None
    error_type: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.status in {"persisted", "already_persisted"}

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "transcript_persistence_status": self.status,
            "transcript_persistence_reason": self.reason,
            "transcript_persisted_count": self.persisted_messages,
            "assistant_message_id": self.assistant_message_id,
            "user_message_id": self.user_message_id,
        }


@dataclass(frozen=True)
class TranscriptHistoryResult:
    """Truthful result of one tenant-scoped durable transcript read."""

    status: str
    conversation_id: str
    messages: tuple[Message, ...] = ()
    reason: Optional[str] = None
    error_type: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.status in {"loaded", "empty", "not_found"}

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "conversation_history_status": self.status,
            "conversation_history_count": len(self.messages),
            "conversation_history_reason": self.reason,
        }


class ConversationRuntimeGateway:
    """Runtime-facing adapter over the canonical ConversationRepository."""

    def __init__(self, repository: Optional[ConversationRepository] = None) -> None:
        if repository is None:
            engine = get_postgres_engine()
            repository = RepositoryFactory(
                session_factory=engine.async_session_factory,
            ).create_conversation_repository()
        self._repository = repository

    async def ensure_conversation(
        self,
        context: ChatExecutionContext,
        *,
        first_user_message: str,
    ) -> str:
        """Ensure the authenticated user owns the tenant-scoped conversation."""
        self._require_identity(context)
        conversation_id = resolve_runtime_conversation_id(context)

        existing = await self._repository.get_conversation(
            conversation_id,
            context.tenant_id,
        )
        if not existing.success:
            raise RuntimeError(existing.error or "conversation_lookup_failed")

        if existing.data is not None:
            if str(existing.data.user_id) != str(context.user_id):
                raise PermissionError("conversation_user_mismatch")
            return conversation_id

        created = await self._repository.create_conversation(
            Conversation(
                id=conversation_id,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                title=(first_user_message.strip()[:120] or None),
                metadata={
                    "session_id": context.session_id,
                    "source": "chat_runtime",
                    "created_request_id": context.request_id,
                    "created_correlation_id": context.correlation_id,
                },
            )
        )
        if not created.success:
            raced = await self._repository.get_conversation(
                conversation_id,
                context.tenant_id,
            )
            if (
                raced.success
                and raced.data is not None
                and str(raced.data.user_id) == str(context.user_id)
            ):
                return conversation_id
            raise RuntimeError(created.error or "conversation_create_failed")

        return conversation_id

    async def ensure_session_snapshot(
        self,
        context: ChatExecutionContext,
        *,
        title: str = "New Conversation",
        message_limit: int = 100,
    ) -> ConversationSnapshot:
        """Ensure and load one tenant/user-owned durable conversation.

        This is a transcript-only operation. It deliberately bypasses semantic
        memory formation and exists so thin API/session surfaces can share the
        same canonical repository authority as ChatRuntime.
        """
        self._require_identity(context)
        conversation_id = await self.ensure_conversation(
            context,
            first_user_message=title,
        )

        conversation_result = await self._repository.get_conversation(
            conversation_id,
            context.tenant_id,
        )
        if not conversation_result.success or conversation_result.data is None:
            raise RuntimeError(
                conversation_result.error or "conversation_lookup_failed"
            )
        if str(conversation_result.data.user_id) != str(context.user_id):
            raise PermissionError("conversation_user_mismatch")

        messages_result = await self._repository.get_messages(
            conversation_id,
            context.tenant_id,
            limit=max(0, int(message_limit)),
            offset=0,
        )
        if not messages_result.success:
            raise RuntimeError(
                messages_result.error or "conversation_history_read_failed"
            )

        return ConversationSnapshot(
            conversation=conversation_result.data,
            messages=tuple(messages_result.data or []),
        )

    async def append_message(
        self,
        context: ChatExecutionContext,
        *,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Message:
        """Append one authorized durable transcript message.

        Unlike completed-turn persistence, this operation supports explicit
        conversation-management requests that intentionally persist a single
        user-authored message. It never invokes semantic-memory formation.
        """
        self._require_message_identity(context)
        conversation_id = resolve_runtime_conversation_id(context)
        message_content = str(content or "").strip()
        if not message_content:
            raise ValueError("conversation_message_empty")

        existing = await self._repository.get_conversation(
            conversation_id,
            context.tenant_id,
        )
        if not existing.success:
            raise RuntimeError(existing.error or "conversation_lookup_failed")
        if existing.data is None:
            raise RuntimeError("conversation_not_found")
        if str(existing.data.user_id) != str(context.user_id):
            raise PermissionError("conversation_user_mismatch")

        message_id = self._message_id(
            context=context,
            conversation_id=conversation_id,
            role=str(role),
        )
        message = Message(
            id=message_id,
            conversation_id=conversation_id,
            tenant_id=context.tenant_id,
            role=str(role),
            content=message_content,
            metadata={
                "request_id": context.request_id,
                "correlation_id": context.correlation_id,
                "session_id": context.session_id,
                "conversation_id": conversation_id,
                "source": "conversation_api",
                **dict(metadata or {}),
            },
        )
        write_result = await self._repository.add_message(message)
        if not write_result.success:
            raise RuntimeError(
                write_result.error or "conversation_message_persistence_failed"
            )
        return message

    async def load_history(
        self,
        context: ChatExecutionContext,
        *,
        limit: int,
    ) -> TranscriptHistoryResult:
        """Load authorized durable transcript rows for prompt continuity.

        Reads never create conversations and never invoke semantic-memory logic.
        Rows produced by the same request identity are excluded so a reconnect or
        exact retry cannot feed its already-persisted turn back into itself.
        """
        conversation_id = resolve_runtime_conversation_id(context)
        try:
            self._require_identity(context)
            existing = await self._repository.get_conversation(
                conversation_id,
                context.tenant_id,
            )
            if not existing.success:
                return TranscriptHistoryResult(
                    status="failed",
                    conversation_id=conversation_id,
                    reason=existing.error or "conversation_lookup_failed",
                )
            if existing.data is None:
                return TranscriptHistoryResult(
                    status="not_found",
                    conversation_id=conversation_id,
                )
            if str(existing.data.user_id) != str(context.user_id):
                return TranscriptHistoryResult(
                    status="rejected",
                    conversation_id=conversation_id,
                    reason="conversation_user_mismatch",
                    error_type="PermissionError",
                )

            requested_limit = max(0, int(limit))
            if requested_limit == 0:
                return TranscriptHistoryResult(
                    status="empty",
                    conversation_id=conversation_id,
                )

            result = await self._repository.get_messages(
                conversation_id,
                context.tenant_id,
                limit=requested_limit,
                offset=0,
            )
            if not result.success:
                return TranscriptHistoryResult(
                    status="failed",
                    conversation_id=conversation_id,
                    reason=result.error or "conversation_history_read_failed",
                )

            messages = tuple(
                message
                for message in list(result.data or [])
                if str(message.metadata.get("request_id") or "")
                != str(context.request_id or "")
            )
            return TranscriptHistoryResult(
                status="loaded" if messages else "empty",
                conversation_id=conversation_id,
                messages=messages,
            )
        except PermissionError as exc:
            return TranscriptHistoryResult(
                status="rejected",
                conversation_id=conversation_id,
                reason=str(exc),
                error_type=type(exc).__name__,
            )
        except Exception as exc:
            logger.exception(
                "Canonical transcript history read failed",
                extra={
                    "conversation_id": conversation_id,
                    "tenant_id": context.tenant_id,
                    "user_id": context.user_id,
                    "correlation_id": context.correlation_id,
                    "error_type": type(exc).__name__,
                },
            )
            return TranscriptHistoryResult(
                status="failed",
                conversation_id=conversation_id,
                reason="conversation_history_read_failed",
                error_type=type(exc).__name__,
            )

    async def persist_completed_turn(
        self,
        context: ChatExecutionContext,
        *,
        user_text: str,
        assistant_text: str,
        response_metadata: Optional[Dict[str, Any]] = None,
    ) -> TranscriptPersistenceResult:
        """Persist one completed user/assistant turn through canonical storage.

        This method must only be called after response generation has completed.
        It deliberately performs no semantic-memory formation.
        """
        conversation_id = resolve_runtime_conversation_id(context)
        user_text = str(user_text or "").strip()
        assistant_text = str(assistant_text or "").strip()

        if not user_text or not assistant_text:
            return TranscriptPersistenceResult(
                status="skipped",
                conversation_id=conversation_id,
                reason="incomplete_turn",
            )

        try:
            conversation_id = await self.ensure_conversation(
                context,
                first_user_message=user_text,
            )
            user_message_id = self._message_id(
                context=context,
                conversation_id=conversation_id,
                role="user",
            )
            assistant_message_id = self._message_id(
                context=context,
                conversation_id=conversation_id,
                role="assistant",
            )

            common_metadata = {
                "request_id": context.request_id,
                "correlation_id": context.correlation_id,
                "session_id": context.session_id,
                "conversation_id": conversation_id,
                "source": "chat_runtime",
            }

            user_write = await self._repository.add_message(
                Message(
                    id=user_message_id,
                    conversation_id=conversation_id,
                    tenant_id=context.tenant_id,
                    role="user",
                    content=user_text,
                    metadata={**common_metadata, "transcript_actor": "user"},
                )
            )
            if not user_write.success:
                return TranscriptPersistenceResult(
                    status="failed",
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    persisted_messages=0,
                    reason=user_write.error or "user_message_persistence_failed",
                )
            user_replay = bool(user_write.metadata.get("idempotent_replay", False))

            assistant_write = await self._repository.add_message(
                Message(
                    id=assistant_message_id,
                    conversation_id=conversation_id,
                    tenant_id=context.tenant_id,
                    role="assistant",
                    content=assistant_text,
                    metadata={
                        **common_metadata,
                        "transcript_actor": "assistant",
                        **dict(response_metadata or {}),
                    },
                )
            )
            if not assistant_write.success:
                return TranscriptPersistenceResult(
                    status="failed",
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    persisted_messages=0 if user_replay else 1,
                    reason=(
                        assistant_write.error
                        or "assistant_message_persistence_failed"
                    ),
                )
            assistant_replay = bool(
                assistant_write.metadata.get("idempotent_replay", False)
            )

            newly_persisted = int(not user_replay) + int(not assistant_replay)
            status = (
                "already_persisted"
                if user_replay and assistant_replay
                else "persisted"
            )
            return TranscriptPersistenceResult(
                status=status,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                persisted_messages=newly_persisted,
            )
        except PermissionError as exc:
            logger.warning(
                "Transcript persistence rejected by conversation ownership",
                extra={
                    "conversation_id": conversation_id,
                    "tenant_id": context.tenant_id,
                    "user_id": context.user_id,
                    "correlation_id": context.correlation_id,
                },
            )
            return TranscriptPersistenceResult(
                status="rejected",
                conversation_id=conversation_id,
                reason=str(exc),
                error_type=type(exc).__name__,
            )
        except RuntimeError as exc:
            reason = str(exc)
            safe_reason = (
                reason
                if reason
                in {
                    "duplicate_conversation_id",
                    "conversation_lookup_failed",
                    "conversation_create_failed",
                }
                else "transcript_persistence_failed"
            )
            logger.warning(
                "Canonical transcript persistence rejected by repository state",
                extra={
                    "conversation_id": conversation_id,
                    "tenant_id": context.tenant_id,
                    "user_id": context.user_id,
                    "correlation_id": context.correlation_id,
                    "error_type": type(exc).__name__,
                    "reason": safe_reason,
                },
            )
            return TranscriptPersistenceResult(
                status="failed",
                conversation_id=conversation_id,
                reason=safe_reason,
                error_type=type(exc).__name__,
            )
        except Exception as exc:
            logger.exception(
                "Canonical transcript persistence failed",
                extra={
                    "conversation_id": conversation_id,
                    "tenant_id": context.tenant_id,
                    "user_id": context.user_id,
                    "correlation_id": context.correlation_id,
                    "error_type": type(exc).__name__,
                },
            )
            return TranscriptPersistenceResult(
                status="failed",
                conversation_id=conversation_id,
                reason="transcript_persistence_failed",
                error_type=type(exc).__name__,
            )

    @staticmethod
    def _message_id(
        *,
        context: ChatExecutionContext,
        conversation_id: str,
        role: str,
    ) -> str:
        """Return stable per-request message identity for retry idempotency."""
        identity = ":".join(
            (
                "ai-karen",
                "transcript",
                context.tenant_id,
                conversation_id,
                context.request_id,
                role,
            )
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, identity))

    @staticmethod
    def _require_message_identity(context: ChatExecutionContext) -> None:
        missing = [
            name
            for name, value in (
                ("tenant_id", context.tenant_id),
                ("user_id", context.user_id),
                ("conversation_id", context.conversation_id),
                ("request_id", context.request_id),
            )
            if not str(value or "").strip()
        ]
        if missing:
            raise ValueError(
                "transcript_message_identity_incomplete:" + ",".join(missing)
            )

    @staticmethod
    def _require_identity(context: ChatExecutionContext) -> None:
        missing = [
            name
            for name, value in (
                ("tenant_id", context.tenant_id),
                ("user_id", context.user_id),
                ("session_id", context.session_id),
                ("request_id", context.request_id),
            )
            if not str(value or "").strip()
        ]
        if missing:
            raise ValueError(
                "transcript_identity_incomplete:" + ",".join(missing)
            )


_gateway: Optional[ConversationRuntimeGateway] = None


def get_conversation_runtime_gateway() -> ConversationRuntimeGateway:
    """Return the process-wide runtime adapter for canonical conversations."""
    global _gateway
    if _gateway is None:
        _gateway = ConversationRuntimeGateway()
    return _gateway


def reset_conversation_runtime_gateway() -> None:
    """Reset the gateway singleton for deterministic tests."""
    global _gateway
    _gateway = None


__all__ = [
    "ConversationRuntimeGateway",
    "ConversationSnapshot",
    "TranscriptHistoryResult",
    "TranscriptPersistenceResult",
    "get_conversation_runtime_gateway",
    "reset_conversation_runtime_gateway",
    "resolve_runtime_conversation_id",
]
