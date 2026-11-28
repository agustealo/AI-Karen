"""Response metadata exposes real CORTEX decisions without changing authority."""
import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext, ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision


def test_personal_recall_metadata_exposes_grounding_truth():
    runtime = ChatRuntime.__new__(ChatRuntime)
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "Where do I grow up?"}],
        context=ChatExecutionContext(
            user_id="user", tenant_id="tenant", session_id="session",
            conversation_id="conversation", request_id="request",
            correlation_id="correlation",
        ),
    )
    decision = ExecutionDecision(
        intent="memory.recall",
        reason_codes=["explicit_personal_memory_recall"],
        policy_constraints={"personal_evidence_attribute": "upbringing_location"},
    )
    md = runtime._build_metadata(
        request, decision,
        {
            "response_source": "authorized_memory_evidence",
            "actual_model": None,
            "evidence_sufficiency": "supported",
        },
        1.0,
        {"memory_recall_count": 1},
    ).to_dict()
    assert md["cortex_intent"] == "memory.recall"
    assert md["personal_evidence_attribute"] == "upbringing_location"
    assert md["personal_recall_grounded"] is True
    assert md["response_source"] == "authorized_memory_evidence"
    assert md["actual_model"] is None
    assert md["correlation_id"] == "correlation"


def test_unrecognized_query_metadata_does_not_claim_recall():
    runtime = ChatRuntime.__new__(ChatRuntime)
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "Hi"}],
        context=ChatExecutionContext(
            user_id="user", tenant_id="tenant", session_id="session",
            conversation_id="conversation", request_id="request",
            correlation_id="correlation",
        ),
    )
    md = runtime._build_metadata(
        request, ExecutionDecision(intent="general_assist"),
        {"response_source": "model_generation", "actual_model": "local"},
        1.0,
    ).to_dict()
    assert md["cortex_intent"] == "general_assist"
    assert md["personal_evidence_attribute"] is None
    assert md["personal_recall_grounded"] is False


@pytest.mark.parametrize("source", [
    "authorized_memory_evidence", "authorized_conversation_evidence",
])
@pytest.mark.parametrize("status", [
    "missing", "ambiguous", "contradictory", "expired", None,
    "supported", "supported_set",
])
def test_grounding_metadata_requires_successful_evidence_sufficiency(source, status):
    runtime = ChatRuntime.__new__(ChatRuntime)
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "What is my name?"}],
        context=ChatExecutionContext(
            user_id="user", tenant_id="tenant", session_id="session",
            conversation_id="conversation", request_id="request",
            correlation_id="correlation",
        ),
    )
    decision = ExecutionDecision(
        intent="memory.recall",
        policy_constraints={"personal_evidence_attribute": "preferred_name"},
    )
    md = runtime._build_metadata(
        request, decision,
        {
            "response_source": source,
            "evidence_sufficiency": status,
            "personal_recall_grounded": True,
            "personal_recall_evidence_source": "forged",
        },
        1.0,
        {"personal_recall_grounded": True},
    ).to_dict()
    supported = status in ("supported", "supported_set")
    assert md["personal_recall_grounded"] is supported
    assert md["personal_recall_evidence_source"] == (source if supported else None)
    assert md["response_source"] == source


@pytest.mark.asyncio
async def test_grounded_claim_requires_exact_selected_revision_and_current_authorization(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from ai_karen_engine.core.context.contracts import (
        ContextEvidence, EvidenceScope, EvidenceSource,
    )
    from ai_karen_engine.platform.memory.postgres.event_source import PostgresEventSource

    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "What is my name?"}],
        context=ChatExecutionContext(
            user_id="user", tenant_id="tenant", session_id="session",
            conversation_id="conversation", request_id="request",
            correlation_id="correlation",
        ),
    )
    decision = ExecutionDecision(
        intent="memory.recall", memory_recall_required=True, memory_top_k=1,
        policy_constraints={"personal_evidence_attribute": "preferred_name"},
    )
    origin = {
        "record_id": "name", "event_id": "event", "record_type": "profile_fact",
        "source": "postgres_profile_fact",
        "record_updated_at": "2026-01-01T00:00:00+00:00",
    }
    unrelated = ContextEvidence(
        evidence_id="other", source=EvidenceSource.MEMORY, content="birthplace: Detroit",
        scope=EvidenceScope(tenant_id="tenant", user_id="user"),
    )
    claimed = ContextEvidence(
        evidence_id="name", source=EvidenceSource.MEMORY, content="preferred_name: Alice",
        scope=EvidenceScope(tenant_id="tenant", user_id="user"),
        metadata={
            "memory_metadata": {"source": "postgres_profile_fact"},
            "canonical_event_origin": origin,
        },
    )
    decision.cognitive_context = SimpleNamespace(
        tenant_id="tenant", user_id="user", authorized_sources=["memory"],
        denied_sources=[], unresolved_sources=[], evidence=[unrelated, claimed],
    )
    answer, meta = ChatRuntime._grounded_personal_response(
        decision, tenant_id="tenant", user_id="user",
    )
    assert "Alice" in answer
    ids = meta["_grounded_memory_ids"]
    assert ids == ("name",)
    authorize = AsyncMock(return_value=True)
    monkeypatch.setattr(PostgresEventSource, "authorize_selected_records", authorize)

    async def check():
        await ChatRuntime._authorize_selected_memory_before_generation(
            request, decision, required_memory_ids=ids,
        )

    # The bounded generation set contains only the unrelated fact.
    with pytest.raises(RuntimeError, match="memory_source_revoked_or_unverifiable"):
        await check()
    authorize.assert_not_awaited()

    decision.memory_top_k = 2
    await check()
    authorize.assert_awaited_once_with(tenant_id="tenant", user_id="user", origins=[origin])

    # A same-ID second evidence row or a different record cannot certify the claim.
    decision.cognitive_context.evidence.append(claimed)
    decision.memory_top_k = 3
    with pytest.raises(RuntimeError, match="memory_source_revoked_or_unverifiable"):
        await check()
    decision.cognitive_context.evidence.pop()
    origin["record_id"] = "different"
    with pytest.raises(RuntimeError, match="memory_source_revoked_or_unverifiable"):
        await check()
    origin["record_id"] = "name"
    authorize.return_value = False
    with pytest.raises(RuntimeError, match="memory_source_revoked_or_unverifiable"):
        await check()

    # The internal receipt cannot leak through final consumer metadata.
    public = ChatRuntime.__new__(ChatRuntime)._build_metadata(
        request, decision, meta, 1.0,
    ).to_dict()
    assert "_grounded_memory_ids" not in public
