"""Typed context handoff: only authorized, current, scoped memory can feed tools."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

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
from ai_karen_engine.core.memory.types import MemoryQuery
from ai_karen_engine.platform.memory.postgres.profile_retriever import PostgresProfileRecallRetriever

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


def test_profile_retriever_entry_preserves_future_validity_window():
    now = datetime.now(timezone.utc)
    valid_until = now + timedelta(days=2)
    row = SimpleNamespace(
        fact_id="fact-1",
        event_id="event-1",
        tenant_id=TENANT,
        user_id=USER,
        category="location",
        attribute="current_location",
        value={"value": "Washington, DC"},
        valid_from=now,
        valid_to=valid_until,
        confidence=0.95,
        source_type="chat",
        source_ref="message-1",
        created_at=now,
        updated_at=now,
    )
    entry = PostgresProfileRecallRetriever._entry(
        row,
        MemoryQuery(
            text="Where am I currently?",
            tenant_id=TENANT,
            user_id=USER,
        ),
    )
    assert entry.content == "current_location: Washington, DC"
    assert entry.expires_at == valid_until


def test_recalled_expiry_is_materialized_into_typed_evidence():
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "What's the weather?"}],
        context=ChatExecutionContext(user_id=USER, tenant_id=TENANT, session_id="s"),
    )
    expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    evidence = RuntimeEvidenceResolver._memory_item_to_evidence(
        {
            "id": "memory-expired",
            "content": "current_location: Washington, DC",
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "expires_at": expired_at.isoformat(),
            "similarity_score": 0.99,
            "memory_type": "semantic",
            "metadata": {"confidence": 0.95},
        },
        request=request,
        retrieved_at=datetime.now(timezone.utc),
    )
    context = CognitiveContext(
        context_id="ctx-expired",
        request_id="req",
        correlation_id="corr",
        tenant_id=TENANT,
        user_id=USER,
        requirements=ContextRequirements(
            request_id="req",
            correlation_id="corr",
            tenant_id=TENANT,
            user_id=USER,
        ),
        authorized_sources=["memory"],
        evidence=[evidence],
    )
    assert evidence.temporal.expires_at == expired_at
    assert RuntimeEvidenceResolver.authorized_semantic_value(
        context,
        tenant_id=TENANT,
        user_id=USER,
        attribute="current_location",
    ) is None


def test_temporal_evidence_parser_accepts_iso_z_and_unix_seconds():
    reference = datetime(2026, 10, 9, 12, 30, tzinfo=timezone.utc)
    parser = RuntimeEvidenceResolver._coerce_datetime
    assert parser("2026-10-09T12:30:00Z") == reference
    assert parser("2026-10-09T12:30:00+00:00") == reference
    assert parser(reference.timestamp()) == reference
    assert parser("not-a-date") is None
