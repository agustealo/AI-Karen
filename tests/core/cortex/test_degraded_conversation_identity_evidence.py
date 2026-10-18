"""Request-local identity evidence survives degraded durable history without fake saves."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from ai_karen_engine.core.context.contracts import (
    CognitiveContext, ContextRequirement, ContextRequirements, EvidenceSource,
)
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext, ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.evidence_resolver import RuntimeEvidenceResolver
from ai_karen_engine.core.runtime.evidence_sufficiency import (
    EvidenceSufficiencyStatus, evaluate_conversation_personal_evidence,
)


def _scenario(*, authorized=True, tenant="tenant-a", contextual_tenant="tenant-a"):
    ctx = ChatExecutionContext(
        tenant_id=tenant, user_id="user-a", session_id="session-a",
        conversation_id="conversation-a", request_id="request-a",
        correlation_id="correlation-a",
    )
    request = ChatExecutionRequest(
        context=ctx,
        messages=[
            {"role": "user", "content": "My name is Zeus"},
            {"role": "assistant", "content": "Hello Zeus"},
            {"role": "user", "content": "What's my name?"},
        ],
    )
    requirement = ContextRequirement(
        source=EvidenceSource.CONVERSATION, capability="conversation.read", max_items=10,
    )
    requirements = ContextRequirements(
        request_id="request-a", correlation_id="correlation-a",
        tenant_id=contextual_tenant, user_id="user-a",
        session_id="session-a", conversation_id="conversation-a",
        requirements=[requirement],
    )
    context = CognitiveContext(
        context_id="context-a", request_id="request-a",
        correlation_id="correlation-a", tenant_id=contextual_tenant,
        user_id="user-a", requirements=requirements,
        authorized_sources=[EvidenceSource.CONVERSATION.value] if authorized else [],
        unresolved_sources=[EvidenceSource.CONVERSATION.value],
    )
    resolver = RuntimeEvidenceResolver.__new__(RuntimeEvidenceResolver)
    resolver._conversation_gateway = SimpleNamespace(
        load_history=AsyncMock(side_effect=RuntimeError("database temporarily unavailable"))
    )
    return resolver, request, context, requirement


def test_authorized_recent_identity_survives_repository_failure_without_durable_claim():
    resolver, request, context, requirement = _scenario()
    asyncio.run(resolver._resolve_conversation(request, context, requirement))
    answer = evaluate_conversation_personal_evidence(
        context, tenant_id="tenant-a", user_id="user-a", attribute="preferred_name"
    )
    assert answer.status is EvidenceSufficiencyStatus.SUPPORTED
    assert answer.value == "Zeus"
    assert context.metadata["conversation_history_degraded"] is True
    assert context.metadata["conversation_history_source"] == "request_ingress_not_durable"
    assert context.metadata["conversation_ingress_fallback_count"] == 1
    assert context.evidence[0].provenance.retrieval_method == "request_ingress_not_durable"
    assert request.messages[-1]["content"] == "What's my name?"


def test_denied_conversation_never_uses_ingress_fallback():
    resolver, request, context, requirement = _scenario(authorized=False)
    asyncio.run(resolver._resolve_conversation(request, context, requirement))
    assert not context.evidence
    assert EvidenceSource.CONVERSATION.value in context.unresolved_sources
    assert evaluate_conversation_personal_evidence(
        context, tenant_id="tenant-a", user_id="user-a", attribute="preferred_name"
    ).status is EvidenceSufficiencyStatus.MISSING


def test_cross_tenant_ingress_is_rejected():
    resolver, request, context, requirement = _scenario(contextual_tenant="tenant-b")
    asyncio.run(resolver._resolve_conversation(request, context, requirement))
    assert not context.evidence
    assert EvidenceSource.CONVERSATION.value in context.unresolved_sources


def test_no_history_is_not_invented_from_the_current_question():
    resolver, request, context, requirement = _scenario()
    request.messages = [{"role": "user", "content": "What's my name?"}]
    asyncio.run(resolver._resolve_conversation(request, context, requirement))
    assert not context.evidence
    assert EvidenceSource.CONVERSATION.value in context.unresolved_sources


def test_previous_assistant_claim_is_not_user_identity_evidence():
    resolver, request, context, requirement = _scenario()
    request.messages = [
        {"role": "assistant", "content": "My name is Zeus"},
        {"role": "user", "content": "What's my name?"},
    ]
    asyncio.run(resolver._resolve_conversation(request, context, requirement))
    assert not context.evidence
