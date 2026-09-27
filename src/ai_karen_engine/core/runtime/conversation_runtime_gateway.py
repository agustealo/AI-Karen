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
        conversation_id = context.conversation_id or normalize_session_id(
            context.session_id
        )

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
        conversation_id = context.conversation_id or normalize_session_id(
            context.session_id
        )
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
    "TranscriptPersistenceResult",
    "get_conversation_runtime_gateway",
    "reset_conversation_runtime_gateway",
]
