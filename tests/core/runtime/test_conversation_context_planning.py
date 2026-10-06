from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ai_karen_engine.config.conversation import reset_conversation_context_settings
from ai_karen_engine.core.context.contracts import EvidenceSource
from ai_karen_engine.core.cortex.context_stages import build_context_requirements
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.policy import (
    PolicyEvaluationRequest,
    RuntimePolicyEnforcer,
)


def _preliminary() -> MagicMock:
    decision = MagicMock()
    decision.memory_recall_required = False
    decision.memory_scope = "user"
    decision.memory_classes = []
    decision.memory_top_k = 5
    decision.intent = "general_assist"
    decision.reasoning_depth = "standard"
    return decision


def _request(*, conversation_id: str | None = "33333333-3333-3333-3333-333333333333") -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "continue"}],
        context=ChatExecutionContext(
            tenant_id="11111111-1111-1111-1111-111111111111",
            user_id="22222222-2222-2222-2222-222222222222",
            session_id="session-a" if conversation_id is not None else None,
            conversation_id=conversation_id,
            request_id="44444444-4444-4444-4444-444444444444",
        ),
    )


def test_stage_one_requests_governed_conversation_history(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KARI_CONVERSATION_HISTORY_LIMIT", "6")
    reset_conversation_context_settings()
    try:
        requirements = build_context_requirements(_request(), _preliminary())
    finally:
        reset_conversation_context_settings()

    assert len(requirements.requirements) == 1
    requirement = requirements.requirements[0]
    assert requirement.source is EvidenceSource.CONVERSATION
    assert requirement.capability == "conversation.read"
    assert requirement.scopes == ["conversation"]
    assert requirement.classes == ["transcript"]
    assert requirement.max_items == 6


def test_stage_one_requests_ranked_continuity_with_memory_read() -> None:
    preliminary = _preliminary()
    preliminary.memory_recall_required = True
    requirements = build_context_requirements(
        _request(conversation_id=None),
        preliminary,
    )

    assert [item.source for item in requirements.requirements] == [
        EvidenceSource.MEMORY,
        EvidenceSource.USER_MODEL,
    ]
    assert [item.capability for item in requirements.requirements] == [
        "memory.read",
        "memory.read",
    ]
    continuity = requirements.requirements[1]
    assert continuity.classes == ["next_need"]
    assert continuity.metadata["mode"] == "suggest_only"


def test_stage_one_skips_conversation_read_without_conversation_identity() -> None:
    requirements = build_context_requirements(
        _request(conversation_id=None),
        _preliminary(),
    )

    assert requirements.requirements == []


def test_invalid_conversation_history_limit_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KARI_CONVERSATION_HISTORY_LIMIT", "bogus")
    reset_conversation_context_settings()
    try:
        with pytest.raises(RuntimeError, match="must be an integer"):
            build_context_requirements(_request(), _preliminary())
    finally:
        reset_conversation_context_settings()


def test_oversized_conversation_history_limit_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KARI_CONVERSATION_HISTORY_LIMIT", "501")
    reset_conversation_context_settings()
    try:
        with pytest.raises(RuntimeError, match="must not exceed 500"):
            build_context_requirements(_request(), _preliminary())
    finally:
        reset_conversation_context_settings()


@pytest.mark.asyncio
async def test_runtime_policy_authorizes_conversation_read_as_distinct_capability() -> None:
    policy = RuntimePolicyEnforcer()

    decision = await policy.evaluate(
        PolicyEvaluationRequest(
            user_id="22222222-2222-2222-2222-222222222222",
            tenant_id="11111111-1111-1111-1111-111111111111",
            session_id="session-a",
            correlation_id="55555555-5555-5555-5555-555555555555",
            action="context.resolve",
            requested_capabilities=["conversation.read"],
        )
    )

    assert decision.allowed is True
    assert decision.allowed_capabilities == ["conversation.read"]
    assert decision.denied_capabilities == []
