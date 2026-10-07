from __future__ import annotations

from typing import Optional, Sequence

import pytest

from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    ConversationRuntimeGateway,
    resolve_runtime_conversation_id,
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
            and (query.user_id is None or conversation.user_id == query.user_id)
            and (query.is_active is None or conversation.is_active == query.is_active)
        ]
        return RepositoryResult(success=True, data=rows)

    async def get_conversation_by_session(
        self,
        session_id: str,
        tenant_id: str,
        user_id: str,
    ) -> RepositoryResult[Optional[Conversation]]:
        for (row_tenant_id, _), conversation in self.conversations.items():
            if (
                row_tenant_id == tenant_id
                and conversation.user_id == user_id
                and conversation.session_id == session_id
            ):
                return RepositoryResult(success=True, data=conversation)
        return RepositoryResult(success=True, data=None)

    async def count_conversations(
        self,
        query: ConversationQuery,
    ) -> RepositoryResult[int]:
        listed = await self.list_conversations(query)
        return RepositoryResult(success=True, data=len(listed.data or []))

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
    session_id: str = "session-a",
    conversation_id: Optional[str] = "22222222-2222-2222-2222-222222222222",
) -> ChatExecutionContext:
    return ChatExecutionContext(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        conversation_id=conversation_id,
        request_id=request_id,
        correlation_id="correlation-1",
    )


def test_explicit_conversation_id_remains_authoritative() -> None:
    context = _context()
    assert resolve_runtime_conversation_id(context) == context.conversation_id


def test_derived_conversation_identity_is_stable_within_tenant() -> None:
    first = resolve_runtime_conversation_id(
        _context(conversation_id=None, tenant_id="tenant-a", session_id="shared-session")
    )
    second = resolve_runtime_conversation_id(
        _context(conversation_id=None, tenant_id="tenant-a", session_id="shared-session")
    )
    assert first == second


def test_derived_conversation_identity_is_distinct_across_tenants() -> None:
    tenant_a = resolve_runtime_conversation_id(
        _context(conversation_id=None, tenant_id="tenant-a", session_id="shared-session")
    )
    tenant_b = resolve_runtime_conversation_id(
        _context(conversation_id=None, tenant_id="tenant-b", session_id="shared-session")
    )
    assert tenant_a != tenant_b


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
async def test_history_load_returns_previous_completed_turn_for_next_request() -> None:
    repository = _Repository()
    gateway = ConversationRuntimeGateway(repository=repository)

    first_context = _context(request_id="request-1")
    persisted = await gateway.persist_completed_turn(
        first_context,
        user_text="My workshop is on the east side.",
        assistant_text="I will keep that conversation context.",
    )
    assert persisted.status == "persisted"

    history = await gateway.load_history(
        _context(request_id="request-2"),
        limit=10,
    )

    assert history.status == "loaded"
    assert [message.role for message in history.messages] == ["user", "assistant"]
    assert [message.content for message in history.messages] == [
        "My workshop is on the east side.",
        "I will keep that conversation context.",
    ]


@pytest.mark.asyncio
async def test_history_load_filters_rows_from_same_request_identity() -> None:
    repository = _Repository()
    gateway = ConversationRuntimeGateway(repository=repository)
    context = _context(request_id="request-1")

    persisted = await gateway.persist_completed_turn(
        context,
        user_text="hello",
        assistant_text="hi",
    )
    assert persisted.status == "persisted"

    history = await gateway.load_history(context, limit=10)

    assert history.status == "empty"
    assert history.messages == ()


@pytest.mark.asyncio
async def test_history_load_rejects_wrong_user_in_same_tenant() -> None:
    repository = _Repository()
    owner_context = _context(user_id="user-a", request_id="request-1")
    conversation_id = owner_context.conversation_id or ""
    repository.conversations[(owner_context.tenant_id, conversation_id)] = Conversation(
        id=conversation_id,
        tenant_id=owner_context.tenant_id,
        user_id="user-a",
    )
    gateway = ConversationRuntimeGateway(repository=repository)

    history = await gateway.load_history(
        _context(user_id="user-b", request_id="request-2"),
        limit=10,
    )

    assert history.status == "rejected"
    assert history.reason == "conversation_user_mismatch"
    assert history.messages == ()


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

@pytest.mark.asyncio
async def test_session_snapshot_uses_canonical_repository_without_semantic_memory() -> None:
    repository = _Repository()
    gateway = ConversationRuntimeGateway(repository=repository)
    context = _context(
        conversation_id=None,
        session_id="presentation-session",
        request_id="request-snapshot",
    )

    snapshot = await gateway.ensure_session_snapshot(context)

    assert snapshot.conversation.tenant_id == "tenant-a"
    assert snapshot.conversation.user_id == "user-a"
    assert snapshot.conversation.session_id == "presentation-session"
    assert "session_id" not in snapshot.conversation.metadata
    assert snapshot.messages == ()


@pytest.mark.asyncio
async def test_append_message_enforces_conversation_user_ownership() -> None:
    repository = _Repository()
    owner_context = _context(
        request_id="request-owner",
        session_id="presentation-session",
    )
    gateway = ConversationRuntimeGateway(repository=repository)
    snapshot = await gateway.ensure_session_snapshot(owner_context)

    message = await gateway.append_message(
        _context(
            request_id="request-message",
            session_id=None,
            conversation_id=snapshot.conversation.id,
        ),
        role="user",
        content="This is durable presentation transcript evidence.",
        metadata={"ui_source": "web"},
    )

    assert message.role == "user"
    assert message.metadata["source"] == "conversation_api"
    assert repository.messages == [message]

    with pytest.raises(PermissionError, match="conversation_user_mismatch"):
        await gateway.append_message(
            _context(
                user_id="user-b",
                request_id="request-wrong-user",
                session_id=None,
                conversation_id=snapshot.conversation.id,
            ),
            role="user",
            content="This must not cross the user boundary.",
        )

@pytest.mark.asyncio
async def test_conversation_update_requires_same_user_and_preserves_canonical_fields() -> None:
    repository = _Repository()
    context = _context()
    original = Conversation(
        id=context.conversation_id or "",
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        session_id="session-a",
        title="Original",
        summary="Keep me",
        tags=["durable"],
        metadata={"source": "chat_runtime"},
    )
    repository.conversations[(context.tenant_id, original.id)] = original
    gateway = ConversationRuntimeGateway(repository=repository)

    updated = await gateway.update_conversation(
        context,
        title="Renamed",
    )

    assert updated.title == "Renamed"
    assert updated.summary == "Keep me"
    assert updated.tags == ["durable"]
    assert updated.session_id == "session-a"
    assert "session_id" not in updated.metadata

    with pytest.raises(PermissionError, match="conversation_user_mismatch"):
        await gateway.update_conversation(
            _context(user_id="user-b"),
            title="Forbidden",
        )

    assert repository.conversations[(context.tenant_id, original.id)].title == "Renamed"


@pytest.mark.asyncio
async def test_conversation_delete_requires_same_user() -> None:
    repository = _Repository()
    context = _context()
    conversation_id = context.conversation_id or ""
    repository.conversations[(context.tenant_id, conversation_id)] = Conversation(
        id=conversation_id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        title="Owned",
    )
    gateway = ConversationRuntimeGateway(repository=repository)

    with pytest.raises(PermissionError, match="conversation_user_mismatch"):
        await gateway.delete_conversation(_context(user_id="user-b"))

    assert (context.tenant_id, conversation_id) in repository.conversations

    assert await gateway.delete_conversation(context) is True
    assert (context.tenant_id, conversation_id) not in repository.conversations

