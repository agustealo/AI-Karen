from __future__ import annotations

from datetime import datetime

import pytest

from ai_karen_engine.core.context.contracts import (
    CognitiveContext,
    ContextRequirement,
    ContextRequirements,
    EvidenceSource,
)
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    TranscriptHistoryResult,
)
from ai_karen_engine.core.runtime.evidence_resolver import RuntimeEvidenceResolver
from ai_karen_engine.services.database.repositories.conversation_repository import Message


class _ConversationGateway:
    def __init__(self, result: TranscriptHistoryResult) -> None:
        self.result = result
        self.calls: list[tuple[str, int]] = []

    async def load_history(
        self,
        context: ChatExecutionContext,
        *,
        limit: int,
    ) -> TranscriptHistoryResult:
        self.calls.append((context.conversation_id or "", limit))
        return self.result


def _request(messages: list[dict[str, str]]) -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=messages,
        context=ChatExecutionContext(
            tenant_id="11111111-1111-1111-1111-111111111111",
            user_id="22222222-2222-2222-2222-222222222222",
            session_id="session-a",
            conversation_id="33333333-3333-3333-3333-333333333333",
            request_id="44444444-4444-4444-4444-444444444444",
            correlation_id="55555555-5555-5555-5555-555555555555",
        ),
    )


def _context(request: ChatExecutionRequest, max_items: int = 8) -> CognitiveContext:
    requirement = ContextRequirement(
        source=EvidenceSource.CONVERSATION,
        capability="conversation.read",
        scopes=["conversation"],
        classes=["transcript"],
        max_items=max_items,
    )
    requirements = ContextRequirements(
        request_id=request.context.request_id or "",
        correlation_id=request.context.correlation_id,
        tenant_id=request.context.tenant_id,
        user_id=request.context.user_id,
        session_id=request.context.session_id,
        conversation_id=request.context.conversation_id,
        requirements=[requirement],
    )
    return CognitiveContext(
        context_id="context-1",
        request_id=request.context.request_id or "",
        correlation_id=request.context.correlation_id,
        tenant_id=request.context.tenant_id,
        user_id=request.context.user_id,
        requirements=requirements,
        authorized_sources=[EvidenceSource.CONVERSATION.value],
        unresolved_sources=[EvidenceSource.CONVERSATION.value],
        policy_decision_id="policy-1",
    )


def _history_result(request: ChatExecutionRequest) -> TranscriptHistoryResult:
    conversation_id = request.context.conversation_id or ""
    tenant_id = request.context.tenant_id
    return TranscriptHistoryResult(
        status="loaded",
        conversation_id=conversation_id,
        messages=(
            Message(
                id="66666666-6666-6666-6666-666666666666",
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                role="user",
                content="My workshop is on the east side.",
                created_at=datetime(2026, 9, 27, 10, 0, 0),
                metadata={"request_id": "previous-request"},
            ),
            Message(
                id="77777777-7777-7777-7777-777777777777",
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                role="assistant",
                content="I will retain that conversation context.",
                created_at=datetime(2026, 9, 27, 10, 0, 1),
                metadata={"request_id": "previous-request"},
            ),
        ),
    )


@pytest.mark.asyncio
async def test_durable_transcript_is_typed_evidence_and_injected_for_reload() -> None:
    request = _request([{"role": "user", "content": "Which side is my workshop on?"}])
    gateway = _ConversationGateway(_history_result(request))
    resolver = RuntimeEvidenceResolver(conversation_gateway=gateway)
    cognitive_context = _context(request)

    resolved = await resolver.resolve(request, cognitive_context)

    assert gateway.calls == [(request.context.conversation_id or "", 8)]
    assert EvidenceSource.CONVERSATION.value not in resolved.unresolved_sources
    assert [evidence.source for evidence in resolved.evidence] == [
        EvidenceSource.CONVERSATION,
        EvidenceSource.CONVERSATION,
    ]
    assert [evidence.metadata["role"] for evidence in resolved.evidence] == [
        "user",
        "assistant",
    ]
    assert request.messages == [
        {"role": "user", "content": "My workshop is on the east side."},
        {
            "role": "assistant",
            "content": "I will retain that conversation context.",
        },
        {"role": "user", "content": "Which side is my workshop on?"},
    ]
    assert request.metadata["conversation_history_source"] == "canonical_repository"
    assert resolved.metadata["conversation_history_injected"] is True
    assert resolved.metadata["conversation_history_count"] == 2


@pytest.mark.asyncio
async def test_ingress_supplied_assistant_history_is_not_duplicated() -> None:
    request = _request(
        [
            {"role": "user", "content": "My workshop is on the east side."},
            {
                "role": "assistant",
                "content": "I will retain that conversation context.",
            },
            {"role": "user", "content": "Which side is my workshop on?"},
        ]
    )
    original_messages = list(request.messages)
    gateway = _ConversationGateway(_history_result(request))
    resolver = RuntimeEvidenceResolver(conversation_gateway=gateway)

    resolved = await resolver.resolve(request, _context(request))

    assert request.messages == original_messages
    assert request.metadata["conversation_history_source"] == "ingress"
    assert resolved.metadata["conversation_history_injected"] is False
    assert len(resolved.evidence) == 2


@pytest.mark.asyncio
async def test_rejected_conversation_history_remains_unresolved_and_is_not_injected() -> None:
    request = _request([{"role": "user", "content": "hello"}])
    rejected = TranscriptHistoryResult(
        status="rejected",
        conversation_id=request.context.conversation_id or "",
        reason="conversation_user_mismatch",
        error_type="PermissionError",
    )
    resolver = RuntimeEvidenceResolver(
        conversation_gateway=_ConversationGateway(rejected)
    )
    cognitive_context = _context(request)

    resolved = await resolver.resolve(request, cognitive_context)

    assert EvidenceSource.CONVERSATION.value in resolved.unresolved_sources
    assert resolved.evidence == []
    assert request.messages == [{"role": "user", "content": "hello"}]
    assert resolved.metadata["conversation_history_status"] == "rejected"
    assert resolved.metadata["conversation_history_degraded"] is True
    assert resolved.metadata["conversation_history_error_type"] == "PermissionError"


@pytest.mark.asyncio
async def test_empty_conversation_history_is_resolved_without_degradation() -> None:
    request = _request([{"role": "user", "content": "hello"}])
    empty = TranscriptHistoryResult(
        status="empty",
        conversation_id=request.context.conversation_id or "",
    )
    resolver = RuntimeEvidenceResolver(conversation_gateway=_ConversationGateway(empty))
    cognitive_context = _context(request)

    resolved = await resolver.resolve(request, cognitive_context)

    assert EvidenceSource.CONVERSATION.value not in resolved.unresolved_sources
    assert resolved.evidence == []
    assert resolved.metadata["conversation_history_status"] == "empty"
    assert resolved.metadata["conversation_history_degraded"] is False
