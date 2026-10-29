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
        self, conversation_id: str, tenant_id: str, *, user_id: str
    ) -> RepositoryResult[bool]:
        key = (tenant_id, conversation_id)
        existing = self.conversations.get(key)
        if existing is None or existing.user_id != user_id:
            return RepositoryResult(success=False, error="conversation_not_found")
        self.conversations.pop(key)
        return RepositoryResult(success=True, data=True)

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

    async def add_completed_turn(
        self, user_message: Message, assistant_message: Message
    ) -> RepositoryResult[int]:
        # Model the production PostgreSQL parent-row scope check. Database
        # concurrency/transaction atomicity still needs the live SQL burn.
        conversation = self.conversations.get(
            (user_message.tenant_id, user_message.conversation_id)
        )
        if conversation is None:
            return RepositoryResult(success=False, error="conversation_not_found")
        requested_scope = user_message.metadata.get("persona_scope_id")
        if requested_scope != assistant_message.metadata.get("persona_scope_id"):
            return RepositoryResult(success=False, error="invalid_completed_turn")
        stored_scope = conversation.metadata.get("persona_scope_id")
        if stored_scope is None and requested_scope:
            if any(m.conversation_id == conversation.id for m in self.messages):
                return RepositoryResult(
                    success=False, error="conversation_persona_scope_mismatch"
                )
            conversation.metadata["persona_scope_id"] = requested_scope
        elif stored_scope != requested_scope:
            return RepositoryResult(
                success=False, error="conversation_persona_scope_mismatch"
            )
        if self.fail_add_role in {"user", "assistant"}:
            return RepositoryResult(
                success=False, error=f"{self.fail_add_role}_write_failed"
            )
        for candidate in (user_message, assistant_message):
            for prior in self.messages:
                if prior.id == candidate.id and (
                    prior.tenant_id != candidate.tenant_id
                    or prior.conversation_id != candidate.conversation_id
                    or prior.role != candidate.role
                    or prior.content != candidate.content
                ):
                    return RepositoryResult(
                        success=False, error="message_idempotency_conflict"
                    )
        replays = [
            any(prior.id == msg.id for prior in self.messages)
            for msg in (user_message, assistant_message)
        ]
        if sum(replays) == 1:
            return RepositoryResult(
                success=False, error="incomplete_turn_replay"
            )
        if all(replays):
            return RepositoryResult(
                success=True, data=0,
                metadata={"idempotent_replay": True},
            )
        self.messages.extend((user_message, assistant_message))
        return RepositoryResult(success=True, data=2)

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
async def test_assistant_failure_rolls_back_both_messages() -> None:
    repository = _Repository()
    repository.fail_add_role = "assistant"
    gateway = ConversationRuntimeGateway(repository=repository)

    result = await gateway.persist_completed_turn(
        _context(),
        user_text="hello",
        assistant_text="hi",
    )

    assert result.status == "failed"
    assert result.persisted_messages == 0
    assert result.reason == "assistant_write_failed"
    assert repository.messages == []


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



@pytest.mark.asyncio
async def test_presentation_survives_canonical_history_and_retry_without_duplicate() -> None:
    """The assistant's structured evidence stays in its owned durable message."""
    repository = _Repository()
    gateway = ConversationRuntimeGateway(repository=repository)
    envelope = {
        "schema_version": 1,
        "presentation_id": "weather-request-1",
        "component_type": "weather.observation",
        "evidence_ref": "request-1:weather-tool",
        "data": {"location": "Detroit", "temperature_f": 60.3},
    }
    metadata = {"structured_content": {"presentation": envelope}}
    initial = await gateway.persist_completed_turn(
        _context(request_id="weather-request"),
        user_text="What's the weather in Detroit?",
        assistant_text="The observed temperature is 60.3°F.",
        response_metadata=metadata,
    )
    assert initial.status == "persisted"
    assert len(repository.messages) == 2
    assistant = repository.messages[1]
    assert assistant.role == "assistant"
    assert assistant.metadata["structured_content"]["presentation"] == envelope

    replay = await gateway.persist_completed_turn(
        _context(request_id="weather-request"),
        user_text="What's the weather in Detroit?",
        assistant_text="The observed temperature is 60.3°F.",
        response_metadata=metadata,
    )
    assert replay.status == "already_persisted"
    assert len(repository.messages) == 2

    history = await gateway.load_history(_context(request_id="next-request"), limit=10)
    assert history.status == "loaded"
    assert history.messages[-1].metadata["structured_content"]["presentation"] == envelope


@pytest.mark.asyncio
async def test_foreign_tenant_cannot_read_persisted_presentation_evidence() -> None:
    repository = _Repository()
    gateway = ConversationRuntimeGateway(repository=repository)
    persisted = await gateway.persist_completed_turn(
        _context(request_id="weather-request"),
        user_text="What's the weather in Detroit?",
        assistant_text="Observed temperature: 60.3°F.",
        response_metadata={
            "structured_content": {
                "presentation": {
                    "schema_version": 1,
                    "presentation_id": "weather-request",
                    "component_type": "weather.observation",
                    "evidence_ref": "weather-request:weather-tool",
                    "data": {"location": "Detroit", "temperature_f": 60.3},
                }
            }
        },
    )
    assert persisted.status == "persisted"
    with pytest.raises((PermissionError, RuntimeError, ValueError)):
        await gateway.get_owned_snapshot(
            _context(tenant_id="tenant-other", request_id="foreign-read"),
            message_limit=10,
        )


@pytest.mark.asyncio
async def test_planner_presentation_round_trip_through_durable_gateway_and_api_serializer():
    """Authorized planner data remains the same after storing and re-reading a turn."""
    from types import SimpleNamespace

    from ai_karen_engine.api_routes.chat.conversation import _canonical_snapshot_to_response
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatStreamChunk, ChatStreamEventType
    from ai_karen_engine.core.runtime.ag_ui_event_projection import AGUIEventProjection

    repository = _Repository()
    gateway = ConversationRuntimeGateway(repository=repository)
    envelope = {
        "schema_version": 1,
        "presentation_id": "planner-corr-1",
        "component_type": "planner.task_list",
        "evidence_ref": "planner-owned-read:corr-1",
        "correlation_id": "corr-1",
        "data": {"tasks": [{"id": "task-1", "title": "Review release", "status": "todo"}]},
    }
    result = SimpleNamespace(
        success=True, degraded=False, source="planner", source_id="planner.read",
        payload={"presentation": envelope},
    )
    verified = ChatRuntime._verified_planner_presentation(
        SimpleNamespace(intent="planner.read"),
        SimpleNamespace(allowed_capabilities=["planner.read"]),
        result,
    )
    assert verified == envelope
    projection = AGUIEventProjection(thread_id="owned-thread", run_id="run-1")
    projection.begin()
    events = projection.project(ChatStreamChunk(
        type=ChatStreamEventType.PRESENTATION, content="", correlation_id="corr-1",
        metadata={"presentation": verified, "presentation_verified": True},
    ))
    assert events[0]["value"] == envelope

    persisted = await gateway.persist_completed_turn(
        _context(request_id="planner-request-1"),
        user_text="List my tasks",
        assistant_text="Found 1 planner commitments.",
        response_metadata={"structured_content": {"presentation": verified}},
    )
    assert persisted.status == "persisted"
    snapshot = await gateway.get_owned_snapshot(_context(request_id="planner-read"))
    api_response = _canonical_snapshot_to_response(snapshot)
    assert api_response.messages[-1].structured_content == {"presentation": envelope}
    assert api_response.messages[-1].content == "Found 1 planner commitments."

    with pytest.raises(RuntimeError, match="conversation_not_found"):
        await gateway.get_owned_snapshot(
            _context(tenant_id="tenant-foreign", request_id="foreign-read"),
        )
    with pytest.raises(PermissionError, match="conversation_user_mismatch"):
        await gateway.get_owned_snapshot(
            _context(user_id="user-foreign", request_id="foreign-read"),
        )


@pytest.mark.asyncio
async def test_planner_presentation_write_failure_is_not_reported_as_saved():
    """Failed assistant-message writes must not create a recoverable planner card."""
    repository = _Repository()
    repository.fail_add_role = "assistant"
    gateway = ConversationRuntimeGateway(repository=repository)
    envelope = {
        "schema_version": 1,
        "presentation_id": "planner-request-2",
        "component_type": "planner.task_list",
        "evidence_ref": "planner-owned-read:request-2",
        "data": {"tasks": [{"id": "task-1", "title": "Review release", "status": "todo"}]},
    }
    context = _context(request_id="planner-request-2")
    failed = await gateway.persist_completed_turn(
        context,
        user_text="List my tasks",
        assistant_text="Found 1 planner commitments.",
        response_metadata={"structured_content": {"presentation": envelope}},
    )
    assert failed.status == "failed"
    assert failed.success is False
    assert not [m for m in repository.messages if m.role == "assistant"]
    snapshot = await gateway.get_owned_snapshot(context)
    assert all("presentation" not in m.metadata.get("structured_content", {})
               for m in snapshot.messages)

    repository.fail_add_role = None
    recovered = await gateway.persist_completed_turn(
        context,
        user_text="List my tasks",
        assistant_text="Found 1 planner commitments.",
        response_metadata={"structured_content": {"presentation": envelope}},
    )
    assert recovered.status == "persisted"
    assert len(repository.messages) == 2
    assert (await gateway.get_owned_snapshot(context)).messages[-1].metadata[
        "structured_content"
    ]["presentation"] == envelope



@pytest.mark.asyncio
async def test_history_restores_grounded_presentation_and_model_receipt() -> None:
    repository = _Repository()
    context = _context(request_id="grounded-receipt")
    gateway = ConversationRuntimeGateway(repository=repository)
    metadata = {
        "actual_provider": "ollama",
        "actual_model": "authorized-model",
        "response_source": "grounded_observation_model",
        "structured_content": {
            "presentation": {
                "type": "weather",
                "data": {"temperature": 20, "unit": "celsius"},
            }
        },
    }
    committed = await gateway.persist_completed_turn(
        context,
        user_text="What is the weather?",
        assistant_text="The verified temperature is 20 degrees Celsius.",
        response_metadata=metadata,
    )
    assert committed.success
    history = await gateway.load_history(
        _context(request_id="subsequent-request"), limit=10
    )
    assert history.status == "loaded"
    assistant = next(message for message in history.messages if message.role == "assistant")
    assert assistant.content == "The verified temperature is 20 degrees Celsius."
    for key, value in metadata.items():
        assert assistant.metadata[key] == value
    assert assistant.metadata["request_id"] == context.request_id


@pytest.mark.asyncio
async def test_response_metadata_cannot_override_authorized_transcript_identity() -> None:
    repository = _Repository()
    context = _context(request_id="authorized-request")
    gateway = ConversationRuntimeGateway(repository=repository)
    result = await gateway.persist_completed_turn(
        context,
        user_text="Who owns this conversation?",
        assistant_text="Ownership comes from authenticated context.",
        response_metadata={
            "request_id": "forged-request",
            "correlation_id": "forged-correlation",
            "session_id": "forged-session",
            "conversation_id": "forged-conversation",
            "authorized_user_id": "forged-user",
            "source": "forged-source",
            "transcript_actor": "user",
            "actual_provider": "ollama",
            "actual_model": "test-model",
        },
    )
    assert result.status == "persisted"
    assistant = next(row for row in repository.messages if row.role == "assistant")
    assert assistant.metadata["request_id"] == context.request_id
    assert assistant.metadata["correlation_id"] == context.correlation_id
    assert assistant.metadata["session_id"] == context.session_id
    assert assistant.metadata["conversation_id"] == result.conversation_id
    assert assistant.metadata["authorized_user_id"] == context.user_id
    assert assistant.metadata["source"] == "chat_runtime"
    assert assistant.metadata["transcript_actor"] == "assistant"
    assert assistant.metadata["actual_provider"] == "ollama"
    assert assistant.metadata["actual_model"] == "test-model"


@pytest.mark.asyncio
async def test_restored_turn_retains_grounded_search_execution_receipt() -> None:
    repository = _Repository()
    gateway = ConversationRuntimeGateway(repository=repository)
    receipt = {
        "answer_composition_status": "grounded_model",
        "response_source": "grounded_search_model",
        "actual_provider": "local",
        "actual_model": "verified-model",
    }
    saved = await gateway.persist_completed_turn(
        _context(request_id="research-1"),
        user_text="Explain the retrieved article with citations.",
        assistant_text="Grounded response with source citation.",
        response_metadata=receipt,
    )
    assert saved.status == "persisted"

    restored = await gateway.load_history(
        _context(request_id="research-2"),
        limit=10,
    )
    assert restored.status == "loaded"
    assistant = next(message for message in restored.messages if message.role == "assistant")
    for key, value in receipt.items():
        assert assistant.metadata[key] == value
    assert all(
        "answer_composition_status" not in message.metadata
        for message in restored.messages if message.role == "user"
    )


@pytest.mark.asyncio
async def test_persona_scope_rejects_switch_to_different_persona_in_same_thread() -> None:
    repository = _Repository()
    gateway = ConversationRuntimeGateway(repository=repository)
    first = await gateway.persist_completed_turn(
        _context(request_id="first"),
        user_text="Private Troy design instructions",
        assistant_text="Troy response",
        persona_scope_id="Troy",
    )
    assert first.status == "persisted"
    conversation = repository.conversations[("tenant-a", _context().conversation_id)]
    assert conversation.metadata["persona_scope_id"] == "Troy"
    assert all(message.metadata["persona_scope_id"] == "Troy" for message in repository.messages)

    same = await gateway.load_history(
        _context(request_id="next"), limit=12, persona_scope_id="Troy",
    )
    assert same.success
    assert len(same.messages) == 2

    for new_scope in ("Morgan", None):
        different = await gateway.load_history(
            _context(request_id="next"), limit=12, persona_scope_id=new_scope,
        )
        assert different.status == "rejected"
        assert different.reason == "conversation_persona_scope_mismatch"

        forbidden = await gateway.persist_completed_turn(
            _context(request_id=f"switch-{new_scope}"),
            user_text="Do not transfer Troy knowledge",
            assistant_text="Not persisted",
            persona_scope_id=new_scope,
        )
        assert forbidden.status == "rejected"
        assert forbidden.reason == "conversation_persona_scope_mismatch"
        assert len(repository.messages) == 2


@pytest.mark.asyncio
async def test_legacy_unattributed_conversation_cannot_be_claimed_by_private_persona() -> None:
    repository = _Repository()
    gateway = ConversationRuntimeGateway(repository=repository)
    legacy = await gateway.persist_completed_turn(
        _context(request_id="legacy"),
        user_text="Legacy user information",
        assistant_text="Legacy assistant information",
    )
    assert legacy.status == "persisted"
    legacy_history = await gateway.load_history(
        _context(request_id="new"), limit=12, persona_scope_id="Troy",
    )
    assert legacy_history.status == "rejected"
    assert legacy_history.messages == ()

    attempted = await gateway.persist_completed_turn(
        _context(request_id="new"),
        user_text="Troy must not inherit legacy context",
        assistant_text="not stored",
        persona_scope_id="Troy",
    )
    assert attempted.status == "rejected"
    assert len(repository.messages) == 2


@pytest.mark.asyncio
async def test_scoped_history_rejects_untagged_legacy_message_even_when_parent_matches() -> None:
    repository = _Repository()
    gateway = ConversationRuntimeGateway(repository=repository)
    persisted = await gateway.persist_completed_turn(
        _context(request_id="first"),
        user_text="Private source",
        assistant_text="Private reply",
        persona_scope_id="Troy",
    )
    assert persisted.status == "persisted"
    # Simulate a legacy conversation API adding an unattributed message.
    repository.messages[0].metadata.pop("persona_scope_id")
    history = await gateway.load_history(
        _context(request_id="second"), limit=12, persona_scope_id="Troy",
    )
    assert history.status == "rejected"
    assert history.reason == "conversation_history_persona_scope_mismatch"
    assert not history.messages


@pytest.mark.asyncio
async def test_new_persona_requires_new_conversation_identity() -> None:
    repository = _Repository()
    gateway = ConversationRuntimeGateway(repository=repository)
    original = _context(request_id="first")
    original_result = await gateway.persist_completed_turn(
        original, user_text="Troy", assistant_text="Original reply",
        persona_scope_id="Troy",
    )
    assert original_result.status == "persisted"
    new_context = _context(
        request_id="new", conversation_id="33333333-3333-3333-3333-333333333333",
    )
    new_result = await gateway.persist_completed_turn(
        new_context, user_text="Morgan", assistant_text="Separate reply",
        persona_scope_id="Morgan",
    )
    assert new_result.status == "persisted"
    morgan = await gateway.load_history(
        _context(request_id="next", conversation_id=new_context.conversation_id),
        limit=12, persona_scope_id="Morgan",
    )
    assert [message.content for message in morgan.messages] == [
        "Morgan", "Separate reply",
    ]


@pytest.mark.asyncio
async def test_empty_session_bootstrap_can_be_claimed_by_first_private_persona():
    repository = _Repository()
    gateway = ConversationRuntimeGateway(repository=repository)
    owner = _context(request_id="bootstrap")
    bootstrapped = await gateway.ensure_session_snapshot(owner, message_limit=0)
    assert bootstrapped.conversation.metadata.get("persona_scope_id") is None

    history = await gateway.load_history(
        _context(request_id="first"), limit=12, persona_scope_id="Troy",
    )
    assert history.status == "empty"
    saved = await gateway.persist_completed_turn(
        _context(request_id="first"),
        user_text="Troy private request", assistant_text="Scoped response",
        persona_scope_id="Troy",
    )
    assert saved.status == "persisted"
    assert bootstrapped.conversation.metadata["persona_scope_id"] == "Troy"

    # UI can still display a user-owned conversation, but a default model
    # cannot reuse its private transcript as prompt continuity.
    snapshot = await gateway.ensure_session_snapshot(owner, message_limit=12)
    assert len(snapshot.messages) == 2
    default_history = await gateway.load_history(
        _context(request_id="second"), limit=12,
    )
    assert default_history.status == "rejected"


@pytest.mark.asyncio
async def test_competing_persona_cannot_claim_already_bound_session_shell():
    repository = _Repository()
    gateway = ConversationRuntimeGateway(repository=repository)
    context = _context()
    await gateway.ensure_session_snapshot(context, message_limit=0)
    first = await gateway.persist_completed_turn(
        _context(request_id="first"), user_text="First", assistant_text="Troy",
        persona_scope_id="Troy",
    )
    second = await gateway.persist_completed_turn(
        _context(request_id="second"), user_text="Second", assistant_text="Morgan",
        persona_scope_id="Morgan",
    )
    assert first.status == "persisted"
    assert second.status == "rejected"
    assert len(repository.messages) == 2
