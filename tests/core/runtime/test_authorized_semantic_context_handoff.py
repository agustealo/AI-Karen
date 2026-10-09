"""Typed context handoff: only authorized, current, scoped memory can feed tools."""
from datetime import datetime, timedelta, timezone

from ai_karen_engine.core.context.contracts import (
    CognitiveContext,
    ContextEvidence,
    ContextRequirements,
    EvidenceContradiction,
    EvidenceContradictionStatus,
    EvidenceScope,
    EvidenceSource,
    EvidenceTemporalContext,
)
from ai_karen_engine.core.cortex.context_stages import build_context_requirements
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext, ChatExecutionRequest
from ai_karen_engine.core.runtime.evidence_resolver import RuntimeEvidenceResolver
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "11111111-1111-1111-1111-111111111111"


def _context(*, authorized=True, user=USER, expired=False, contradiction=False):
    requirements = ContextRequirements(
        request_id="req", correlation_id="corr", tenant_id=TENANT, user_id=USER,
    )
    evidence = ContextEvidence(
        evidence_id="profile-dc", source=EvidenceSource.MEMORY,
        content="current_location: DC",
        scope=EvidenceScope(tenant_id=TENANT, user_id=user),
        temporal=EvidenceTemporalContext(
            expires_at=(
                datetime.now(timezone.utc) - timedelta(days=1)
                if expired else None
            )
        ),
        contradiction=EvidenceContradiction(
            status=(
                EvidenceContradictionStatus.CONFIRMED
                if contradiction else EvidenceContradictionStatus.NONE
            )
        ),
    )
    return CognitiveContext(
        context_id="ctx", request_id="req", correlation_id="corr",
        tenant_id=TENANT, user_id=USER, requirements=requirements,
        authorized_sources=["memory"] if authorized else [],
        evidence=[evidence],
    )


def test_current_authorized_profile_value_is_consumable():
    assert RuntimeEvidenceResolver.authorized_semantic_value(
        _context(), tenant_id=TENANT, user_id=USER, attribute="current_location"
    ) == "DC"


def test_scope_policy_expiry_and_contradiction_fail_closed():
    for ctx in (
        _context(authorized=False),
        _context(user="another-user"),
        _context(expired=True),
        _context(contradiction=True),
    ):
        assert RuntimeEvidenceResolver.authorized_semantic_value(
            ctx, tenant_id=TENANT, user_id=USER, attribute="current_location"
        ) is None


def test_cortex_declares_semantic_role_in_authorized_memory_requirement():
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "What's the weather?"}],
        context=ChatExecutionContext(user_id=USER, tenant_id=TENANT, session_id="s"),
    )
    decision = ExecutionDecision(intent="search.weather", memory_recall_required=True)
    requirements = build_context_requirements(request, decision)
    memory = next(x for x in requirements.requirements if x.source is EvidenceSource.MEMORY)
    assert memory.metadata["semantic_role"] == "location.current"
    assert memory.metadata["retrieval_query"] == "Where am I currently?"
    assert memory.capability == "memory.read"


def test_nonweather_recall_keeps_original_query():
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "What's my name?"}],
        context=ChatExecutionContext(user_id=USER, tenant_id=TENANT, session_id="s"),
    )
    requirements = build_context_requirements(
        request,
        ExecutionDecision(intent="general_assist", memory_recall_required=True),
    )
    memory = next(x for x in requirements.requirements if x.source is EvidenceSource.MEMORY)
    assert memory.metadata == {}
