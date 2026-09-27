from __future__ import annotations

from typing import Optional, Sequence

import pytest

from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    ConversationRuntimeGateway,
)
from ai_karen_engine.services.database.repositories.conversation_repository import (
    Conversation,
    ConversationQuery,
    ConversationRepository,
    Message,
    RepositoryResult,
)


class _Repository(ConversationRepository):
    def __init__(self) -> None:
        self.conversations: dict[tuple[str, str], Conversation] = {}
        self.messages: list[Message] = []
        self.fail_add_role: Optional[str] = None

    async def health_check(self) -> RepositoryResult:
        return RepositoryResult(success=True)

    async def create_conversation(
        self, conversation: Conversation
    ) -> RepositoryResult[str]:
        key = (conversation.tenant_id, conversation.id)
        if key in self.conversations:
            return RepositoryResult(success=False, error="duplicate")
        self.conversations[key] = conversation
        return RepositoryResult(success=True, data=conversation.id)

    async def get_conversation(
        self, conversation_id: str, tenant_id: str
    ) -> RepositoryResult[Optional[Conversation]]:
        return RepositoryResult(
            success=True,
            data=self.conversations.get((tenant_id, conversation_id)),
        )

    async def list_conversations(
        self, query: ConversationQuery
    ) -> RepositoryResult[Sequence[Conversation]]:
        rows = [
            conversation
            for (tenant_id, _), conversation in self.conversations.items()
            if tenant_id == query.tenant_id
        ]
        return RepositoryResult(success=True, data=rows)

    async def update_conversation(
        self, conversation: Conversation
    ) -> RepositoryResult[bool]:
        self.conversations[(conversation.tenant_id, conversation.id)] = conversation
        return RepositoryResult(success=True, data=True)

    async def delete_conversation(
        self, conversation_id: str, tenant_id: str
    ) -> RepositoryResult[bool]:
        return RepositoryResult(
            success=True,
            data=self.conversations.pop((tenant_id, conversation_id), None) is not None,
        )

    async def add_message(self, message: Message) -> RepositoryResult[str]:
        if self.fail_add_role == message.role:
            return RepositoryResult(success=False, error=f"{message.role}_write_failed")

        for existing in self.messages:
            if existing.id != message.id:
                continue
            if (
                existing.tenant_id == message.tenant_id
                and existing.conversation_id == message.conversation_id
                and existing.role == message.role
                and existing.content == message.content
            ):
                return RepositoryResult(
                    success=True,
                    data=message.id,
                    metadata={"idempotent_replay": True},
                )
            return RepositoryResult(success=False, error="message_idempotency_conflict")

        self.messages.append(message)
        return RepositoryResult(
            success=True,
            data=message.id,
            metadata={"idempotent_replay": False},
        )

    async def get_messages(
        self,
        conversation_id: str,
        tenant_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> RepositoryResult[list[Message]]:
        rows = [
            message
            for message in self.messages
            if message.conversation_id == conversation_id
            and message.tenant_id == tenant_id
        ]
        return RepositoryResult(success=True, data=rows[offset : offset + limit])

    async def update_message(self, message: Message) -> RepositoryResult[bool]:
        return RepositoryResult(success=True, data=True)

    async def delete_message(
        self, message_id: str, tenant_id: str
    ) -> RepositoryResult[bool]:
        return RepositoryResult(success=True, data=True)


def _context(
    *,
    tenant_id: str = "tenant-a",
    user_id: str = "user-a",
    request_id: str = "request-1",
) -> ChatExecutionContext:
    return ChatExecutionContext(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id="session-a",
        conversation_id="22222222-2222-2222-2222-222222222222",
        request_id=request_id,
        correlation_id="correlation-1",
    )


@pytest.mark.asyncio
async def test_completed_turn_persists_user_and_assistant_through_one_repository() -> None:
    repository = _Repository()
    gateway = ConversationRuntimeGateway(repository=repository)

    result = await gateway.persist_completed_turn(
        _context(),
        user_text="Remember that I prefer concise answers.",
        assistant_text="Understood.",
        response_metadata={"actual_provider": "local"},
    )

    assert result.status == "persisted"
    assert result.persisted_messages == 2
    assert result.user_message_id
    assert result.assistant_message_id
    assert [message.role for message in repository.messages] == ["user", "assistant"]
    assert repository.messages[0].tenant_id == "tenant-a"
    assert repository.messages[1].metadata["actual_provider"] == "local"


@pytest.mark.asyncio
async def test_retry_of_same_completed_turn_is_already_persisted_without_duplicates() -> None:
    repository = _Repository()
    gateway = ConversationRuntimeGateway(repository=repository)
    context = _context()

    first = await gateway.persist_completed_turn(
        context,
        user_text="hello",
        assistant_text="hi",
    )
    retry = await gateway.persist_completed_turn(
        context,
        user_text="hello",
        assistant_text="hi",
    )

    assert first.status == "persisted"
    assert first.persisted_messages == 2
    assert retry.status == "already_persisted"
    assert retry.persisted_messages == 0
    assert retry.user_message_id == first.user_message_id
    assert retry.assistant_message_id == first.assistant_message_id
    assert len(repository.messages) == 2


@pytest.mark.asyncio
async def test_same_request_identity_with_changed_content_fails_closed() -> None:
    repository = _Repository()
    gateway = ConversationRuntimeGateway(repository=repository)
    context = _context()

    first = await gateway.persist_completed_turn(
        context,
        user_text="hello",
        assistant_text="hi",
    )
    conflict = await gateway.persist_completed_turn(
        context,
        user_text="changed user payload",
        assistant_text="hi",
    )

    assert first.status == "persisted"
    assert conflict.status == "failed"
    assert conflict.reason == "message_idempotency_conflict"
    assert len(repository.messages) == 2


@pytest.mark.asyncio
async def test_message_ids_are_stable_for_same_request_and_change_by_role() -> None:
    context = _context()
    conversation_id = context.conversation_id or ""

    user_first = ConversationRuntimeGateway._message_id(
        context=context,
        conversation_id=conversation_id,
        role="user",
    )
    user_second = ConversationRuntimeGateway._message_id(
        context=context,
        conversation_id=conversation_id,
        role="user",
    )
    assistant = ConversationRuntimeGateway._message_id(
        context=context,
        conversation_id=conversation_id,
        role="assistant",
    )

    assert user_first == user_second
    assert assistant != user_first


@pytest.mark.asyncio
async def test_existing_conversation_rejects_different_user_in_same_tenant() -> None:
    repository = _Repository()
    context = _context()
    repository.conversations[(context.tenant_id, context.conversation_id)] = Conversation(
        id=context.conversation_id,
        tenant_id=context.tenant_id,
        user_id="different-user",
    )
    gateway = ConversationRuntimeGateway(repository=repository)

    result = await gateway.persist_completed_turn(
        context,
        user_text="hello",
        assistant_text="hi",
    )

    assert result.status == "rejected"
    assert result.reason == "conversation_user_mismatch"
    assert repository.messages == []


@pytest.mark.asyncio
async def test_same_conversation_id_is_isolated_by_tenant_lookup() -> None:
    repository = _Repository()
    conversation_id = _context().conversation_id
    repository.conversations[("tenant-b", conversation_id)] = Conversation(
        id=conversation_id,
        tenant_id="tenant-b",
        user_id="user-b",
    )
    gateway = ConversationRuntimeGateway(repository=repository)

    result = await gateway.persist_completed_turn(
        _context(tenant_id="tenant-a", user_id="user-a"),
        user_text="tenant a message",
        assistant_text="tenant a response",
    )

    assert result.status == "persisted"
    assert repository.conversations[("tenant-a", conversation_id)].user_id == "user-a"
    assert repository.conversations[("tenant-b", conversation_id)].user_id == "user-b"
    assert all(message.tenant_id == "tenant-a" for message in repository.messages)


@pytest.mark.asyncio
async def test_assistant_failure_reports_partial_transcript_truth() -> None:
    repository = _Repository()
    repository.fail_add_role = "assistant"
    gateway = ConversationRuntimeGateway(repository=repository)

    result = await gateway.persist_completed_turn(
        _context(),
        user_text="hello",
        assistant_text="hi",
    )

    assert result.status == "failed"
    assert result.persisted_messages == 1
    assert result.reason == "assistant_write_failed"
    assert [message.role for message in repository.messages] == ["user"]


@pytest.mark.asyncio
async def test_incomplete_turn_is_not_persisted() -> None:
    repository = _Repository()
    gateway = ConversationRuntimeGateway(repository=repository)

    result = await gateway.persist_completed_turn(
        _context(),
        user_text="hello",
        assistant_text="",
    )

    assert result.status == "skipped"
    assert result.reason == "incomplete_turn"
    assert repository.messages == []
