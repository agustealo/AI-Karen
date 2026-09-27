from __future__ import annotations

from unittest.mock import MagicMock

import pytest

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


def test_stage_one_requests_governed_conversation_history() -> None:
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "continue"}],
        context=ChatExecutionContext(
            tenant_id="11111111-1111-1111-1111-111111111111",
            user_id="22222222-2222-2222-2222-222222222222",
            session_id="session-a",
            conversation_id="33333333-3333-3333-3333-333333333333",
            request_id="44444444-4444-4444-4444-444444444444",
        ),
        metadata={"conversation_history_limit": 6},
    )

    requirements = build_context_requirements(request, _preliminary())

    assert len(requirements.requirements) == 1
    requirement = requirements.requirements[0]
    assert requirement.source is EvidenceSource.CONVERSATION
    assert requirement.capability == "conversation.read"
    assert requirement.scopes == ["conversation"]
    assert requirement.classes == ["transcript"]
    assert requirement.max_items == 6


def test_stage_one_skips_conversation_read_without_conversation_identity() -> None:
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "hello"}],
        context=ChatExecutionContext(
            tenant_id="11111111-1111-1111-1111-111111111111",
            user_id="22222222-2222-2222-2222-222222222222",
            session_id=None,
            conversation_id=None,
            request_id="44444444-4444-4444-4444-444444444444",
        ),
    )

    requirements = build_context_requirements(request, _preliminary())

    assert requirements.requirements == []


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
