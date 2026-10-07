from __future__ import annotations

from typing import Optional, Sequence

import pytest

from ai_karen_engine.core.context.contracts import EvidenceSource
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    ConversationRuntimeGateway,
)
from ai_karen_engine.core.runtime.decision_pipeline import RuntimeDecisionPipeline
from ai_karen_engine.core.runtime.evidence_resolver import RuntimeEvidenceResolver
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.policy import RuntimePolicyEnforcer
from ai_karen_engine.services.database.repositories.base import RepositoryResult
from ai_karen_engine.services.database.repositories.conversation_repository import (
    Conversation,
    ConversationQuery,
    ConversationRepository,
    Message,
)


class _DurableConversationRepository(ConversationRepository):
    """Production-shaped durable store used to prove runtime continuity.

    The store intentionally enforces the production invariants relevant to this
    integration contract: conversation ids are globally unique, reads are tenant
    scoped, and deterministic message ids are idempotent only for identical
    tenant/conversation/role/content tuples.
    """

    def __init__(self) -> None:
        self.conversations: dict[str, Conversation] = {}
        self.messages: dict[str, Message] = {}

    async def health_check(self) -> RepositoryResult:
        return RepositoryResult(success=True)

    async def create_conversation(
        self,
        conversation: Conversation,
    ) -> RepositoryResult[str]:
        if conversation.id in self.conversations:
            return RepositoryResult(success=False, error="duplicate_conversation_id")
        self.conversations[conversation.id] = conversation
        return RepositoryResult(success=True, data=conversation.id)

    async def get_conversation(
        self,
        conversation_id: str,
        tenant_id: str,
    ) -> RepositoryResult[Optional[Conversation]]:
        conversation = self.conversations.get(conversation_id)
        if conversation is None or conversation.tenant_id != tenant_id:
            return RepositoryResult(success=True, data=None)
        return RepositoryResult(success=True, data=conversation)

    async def list_conversations(
        self,
        query: ConversationQuery,
    ) -> RepositoryResult[Sequence[Conversation]]:
        rows = [
            conversation
            for conversation in self.conversations.values()
            if conversation.tenant_id == query.tenant_id
            and (query.user_id is None or conversation.user_id == query.user_id)
        ]
        return RepositoryResult(success=True, data=rows[: query.limit])

    async def get_conversation_by_session(
        self,
        session_id: str,
        tenant_id: str,
        user_id: str,
    ) -> RepositoryResult[Optional[Conversation]]:
        rows = [
            conversation
            for conversation in self.conversations.values()
            if conversation.tenant_id == tenant_id
            and conversation.user_id == user_id
            and str((conversation.metadata or {}).get("session_id") or "") == session_id
        ]
        rows.sort(key=lambda conversation: conversation.updated_at, reverse=True)
        return RepositoryResult(success=True, data=rows[0] if rows else None)

    async def count_conversations(
        self,
        query: ConversationQuery,
    ) -> RepositoryResult[int]:
        rows = [
            conversation
            for conversation in self.conversations.values()
            if conversation.tenant_id == query.tenant_id
            and (query.user_id is None or conversation.user_id == query.user_id)
            and (
                query.is_active is None
                or conversation.is_active is query.is_active
            )
        ]
        return RepositoryResult(success=True, data=len(rows))

    async def update_conversation(
        self,
        conversation: Conversation,
    ) -> RepositoryResult[bool]:
        existing = self.conversations.get(conversation.id)
        if existing is None or existing.tenant_id != conversation.tenant_id:
            return RepositoryResult(success=True, data=False)
        self.conversations[conversation.id] = conversation
        return RepositoryResult(success=True, data=True)

    async def delete_conversation(
        self,
        conversation_id: str,
        tenant_id: str,
    ) -> RepositoryResult[bool]:
        existing = self.conversations.get(conversation_id)
        if existing is None or existing.tenant_id != tenant_id:
            return RepositoryResult(success=True, data=False)
        del self.conversations[conversation_id]
        self.messages = {
            message_id: message
            for message_id, message in self.messages.items()
            if message.conversation_id != conversation_id
        }
        return RepositoryResult(success=True, data=True)

    async def add_message(self, message: Message) -> RepositoryResult[str]:
        conversation = self.conversations.get(message.conversation_id)
        if conversation is None or conversation.tenant_id != message.tenant_id:
            return RepositoryResult(
                success=False,
                error="conversation_not_found_or_tenant_mismatch",
            )

        existing = self.messages.get(message.id)
        if existing is not None:
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
            return RepositoryResult(
                success=False,
                error="message_idempotency_conflict",
            )

        self.messages[message.id] = message
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
        conversation = self.conversations.get(conversation_id)
        if conversation is None or conversation.tenant_id != tenant_id:
            return RepositoryResult(success=True, data=[])
        rows = sorted(
            (
                message
                for message in self.messages.values()
                if message.conversation_id == conversation_id
                and message.tenant_id == tenant_id
            ),
            key=lambda message: message.created_at,
        )
        return RepositoryResult(success=True, data=rows[offset : offset + limit])

    async def update_message(self, message: Message) -> RepositoryResult[bool]:
        existing = self.messages.get(message.id)
        if existing is None or existing.tenant_id != message.tenant_id:
            return RepositoryResult(success=True, data=False)
        self.messages[message.id] = message
        return RepositoryResult(success=True, data=True)

    async def delete_message(
        self,
        message_id: str,
        tenant_id: str,
    ) -> RepositoryResult[bool]:
        existing = self.messages.get(message_id)
        if existing is None or existing.tenant_id != tenant_id:
            return RepositoryResult(success=True, data=False)
        del self.messages[message_id]
        return RepositoryResult(success=True, data=True)


class _DeterministicCortex:
    """Cognitive stage fixture; authorization and evidence resolution stay real."""

    async def decide(self, request: ChatExecutionRequest) -> ExecutionDecision:
        return ExecutionDecision(
            intent="general_assist",
            memory_recall_required=False,
            memory_write_allowed=False,
            required_capabilities=[],
            forbidden_capabilities=[],
            policy_constraints={"memory_write_requested": False},
        )


def _context(
    *,
    tenant_id: str,
    user_id: str,
    session_id: str,
    request_id: str,
    conversation_id: Optional[str] = None,
) -> ChatExecutionContext:
    return ChatExecutionContext(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        conversation_id=conversation_id,
        request_id=request_id,
        correlation_id=f"correlation-{request_id}",
    )


@pytest.mark.asyncio
async def test_turn_two_after_runtime_reload_consumes_turn_one_durable_transcript() -> None:
    repository = _DurableConversationRepository()

    turn_one_context = _context(
        tenant_id="11111111-1111-1111-1111-111111111111",
        user_id="22222222-2222-2222-2222-222222222222",
        session_id="stable-session",
        request_id="33333333-3333-3333-3333-333333333333",
    )
    first_runtime_gateway = ConversationRuntimeGateway(repository=repository)
    persisted = await first_runtime_gateway.persist_completed_turn(
        turn_one_context,
        user_text="My workshop is on the east side.",
        assistant_text="I will use that conversation context.",
    )

    assert persisted.status == "persisted"
    assert persisted.persisted_messages == 2
    assert turn_one_context.conversation_id == persisted.conversation_id

    # Simulate a fresh runtime process boundary: new context, gateway, resolver,
    # and decision pipeline, with only the durable repository surviving.
    turn_two_context = _context(
        tenant_id=turn_one_context.tenant_id,
        user_id=turn_one_context.user_id,
        session_id=turn_one_context.session_id or "",
        request_id="44444444-4444-4444-4444-444444444444",
    )
    turn_two_request = ChatExecutionRequest(
        messages=[
            {
                "role": "user",
                "content": "Which side is my workshop on?",
            }
        ],
        context=turn_two_context,
    )
    reloaded_gateway = ConversationRuntimeGateway(repository=repository)
    resolver = RuntimeEvidenceResolver(conversation_gateway=reloaded_gateway)
    pipeline = RuntimeDecisionPipeline(
        cortex=_DeterministicCortex(),
        policy=RuntimePolicyEnforcer(),
        evidence_resolver=resolver,
    )

    decision = await pipeline.decide(turn_two_request)

    assert turn_two_context.conversation_id == turn_one_context.conversation_id
    assert turn_two_request.messages == [
        {"role": "user", "content": "My workshop is on the east side."},
        {
            "role": "assistant",
            "content": "I will use that conversation context.",
        },
        {"role": "user", "content": "Which side is my workshop on?"},
    ]
    assert turn_two_request.metadata["conversation_history_source"] == (
        "canonical_repository"
    )
    assert decision.cognitive_context is not None
    assert decision.cognitive_context.metadata["conversation_history_status"] == (
        "loaded"
    )
    assert decision.cognitive_context.metadata["conversation_history_injected"] is True
    assert [
        item.content
        for item in decision.cognitive_context.evidence
        if item.source is EvidenceSource.CONVERSATION
    ] == [
        "My workshop is on the east side.",
        "I will use that conversation context.",
    ]
    assert "conversation.read" in decision.required_capabilities
    assert "context_conversation_evidence_available" in decision.reason_codes


@pytest.mark.asyncio
async def test_cross_tenant_explicit_conversation_attack_cannot_read_append_or_replay() -> None:
    repository = _DurableConversationRepository()
    tenant_a_context = _context(
        tenant_id="11111111-1111-1111-1111-111111111111",
        user_id="22222222-2222-2222-2222-222222222222",
        session_id="shared-session",
        request_id="33333333-3333-3333-3333-333333333333",
    )
    tenant_a_gateway = ConversationRuntimeGateway(repository=repository)
    persisted = await tenant_a_gateway.persist_completed_turn(
        tenant_a_context,
        user_text="Tenant A secret context.",
        assistant_text="Tenant A response.",
    )
    assert persisted.status == "persisted"

    attacked_conversation_id = tenant_a_context.conversation_id
    assert attacked_conversation_id

    tenant_b_context = _context(
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        user_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        session_id="shared-session",
        request_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
        conversation_id=attacked_conversation_id,
    )
    tenant_b_gateway = ConversationRuntimeGateway(repository=repository)

    history = await tenant_b_gateway.load_history(tenant_b_context, limit=24)
    append = await tenant_b_gateway.persist_completed_turn(
        tenant_b_context,
        user_text="Attempted cross-tenant append.",
        assistant_text="This must not persist.",
    )
    replay = await tenant_b_gateway.persist_completed_turn(
        tenant_b_context,
        user_text="Attempted cross-tenant append.",
        assistant_text="This must not persist.",
    )

    assert history.status == "not_found"
    assert history.messages == ()
    assert append.status == "failed"
    assert replay.status == "failed"
    assert append.reason == "duplicate_conversation_id"
    assert replay.reason == "duplicate_conversation_id"

    tenant_a_rows = await repository.get_messages(
        attacked_conversation_id,
        tenant_a_context.tenant_id,
    )
    assert tenant_a_rows.success is True
    assert [message.content for message in tenant_a_rows.data or []] == [
        "Tenant A secret context.",
        "Tenant A response.",
    ]
    assert all(
        message.tenant_id == tenant_a_context.tenant_id
        for message in tenant_a_rows.data or []
    )


@pytest.mark.asyncio
async def test_same_tenant_different_user_cannot_recover_existing_conversation() -> None:
    repository = _DurableConversationRepository()
    owner_context = _context(
        tenant_id="11111111-1111-1111-1111-111111111111",
        user_id="22222222-2222-2222-2222-222222222222",
        session_id="owner-session",
        request_id="33333333-3333-3333-3333-333333333333",
    )
    gateway = ConversationRuntimeGateway(repository=repository)
    persisted = await gateway.persist_completed_turn(
        owner_context,
        user_text="Owner-only context.",
        assistant_text="Owner-only response.",
    )
    assert persisted.status == "persisted"

    attacker_context = _context(
        tenant_id=owner_context.tenant_id,
        user_id="99999999-9999-9999-9999-999999999999",
        session_id="attacker-session",
        request_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        conversation_id=owner_context.conversation_id,
    )

    history = await ConversationRuntimeGateway(repository=repository).load_history(
        attacker_context,
        limit=24,
    )

    assert history.status == "rejected"
    assert history.reason == "conversation_user_mismatch"
    assert history.messages == ()
