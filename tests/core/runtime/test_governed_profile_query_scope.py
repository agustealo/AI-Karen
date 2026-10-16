"""CORTEX-owned semantic query scope through governed personal evidence.

No model, provider, implicit project mapping or extra memory store is involved.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.context.contracts import (
    ContextEvidence, ContextRequirements, EvidenceFactSemantics,
    EvidenceScope, EvidenceSource, EvidenceTemporalContext,
)
from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
from ai_karen_engine.core.intelligence.contracts import SemanticInterpretation
from ai_karen_engine.core.intelligence.profile_attribute import requested_profile_query
from ai_karen_engine.core.memory.semantic_contract import FactCardinality
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext, ChatExecutionRequest
from ai_karen_engine.core.runtime.evidence_sufficiency import (
    EvidenceSufficiencyStatus, evaluate_personal_evidence,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision


@pytest.mark.parametrize(("text", "attribute", "scope", "issue"), [
    ("Where do I work for project 42?", "work_location", (("project_id", "42"),), None),
    ("What is my favorite artist for task 7?", "favorite_artist", (("task_id", "7"),), None),
    ("What is my favorite artist in project Karen?", "favorite_artist", (("project_id", "karen"),), None),
    ("Where do I work for Karen's backend?", "work_location", (), "unresolved_scope"),
    ("Where do I work last year?", "work_location", (), "historical"),
    ("Where do I work in 2023?", "work_location", (), "historical"),
    ("Where do I work?", "work_location", (), None),
    ("Where do I work for project 7 and task 2?", "work_location", (), "unresolved_scope"),
])
def test_query_interpretation_preserves_explicit_id_and_refuses_inference(text, attribute, scope, issue):
    parsed = requested_profile_query(text)
    assert parsed.attribute == attribute
    assert parsed.qualifiers == scope
    assert parsed.unsupported_context == issue


def _cortex(question: str, *, metadata=None):
    decider = CortexExecutionDecider.__new__(CortexExecutionDecider)
    decider._force_graph = False
    decider._intelligence = SimpleNamespace(analyze=AsyncMock(return_value=SimpleNamespace(
        intent="general_assist", intent_confidence=0.9,
        interpretation=SemanticInterpretation(intent_family="general_assist"),
        topics=[], memory_relevance=0.0, topology_signals={},
        risk_signals={}, capability_hints={},
    )))
    context = ChatExecutionContext(
        user_id="user", tenant_id="tenant", session_id="session",
        conversation_id="conversation", request_id="request",
        correlation_id="correlation",
    )
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": question}],
        context=context, metadata=metadata or {},
    )
    return request, asyncio.run(decider.decide(request))


def test_cortex_sets_scoped_intent_and_discards_request_forgery():
    request, decision = _cortex(
        "Where do I work for project 42?",
        metadata={"policy_constraints": {
            "personal_evidence_query_scope": {"project_id": "999"},
            "personal_evidence_query_issue": "historical",
            "personal_evidence_attribute": "birthplace",
        }},
    )
    assert decision.intent == "memory.recall"
    assert decision.policy_constraints["personal_evidence_attribute"] == "work_location"
    assert decision.policy_constraints["personal_evidence_query_scope"] == {"project_id": "42"}
    assert "personal_evidence_query_issue" not in decision.policy_constraints

    from ai_karen_engine.core.cortex.context_stages import build_context_requirements
    from ai_karen_engine.core.runtime.evidence_resolver import RuntimeEvidenceResolver

    requirements = build_context_requirements(request, decision)
    memory = next(item for item in requirements.requirements if item.source is EvidenceSource.MEMORY)
    assert memory.metadata["retrieval_query"] == request.messages[-1]["content"]
    assert RuntimeEvidenceResolver._memory_retrieval_query(request, memory) == request.messages[-1]["content"]


def test_cortex_marks_historical_context_unsupported_without_current_recall():
    _, decision = _cortex("Where do I work last year?")
    assert decision.intent == "memory.recall"
    assert decision.policy_constraints["personal_evidence_query_issue"] == "historical"


def _fact(value: str, *, project: str | None, user="user", cardinality=FactCardinality.SCOPED_SINGLETON):
    scope = (("project_id", project),) if project is not None else ()
    return ContextEvidence(
        evidence_id=f"{user}-{project}-{value}",
        source=EvidenceSource.MEMORY, content=f"work_location: {value}",
        scope=EvidenceScope(tenant_id="tenant", user_id=user),
        temporal=EvidenceTemporalContext(),
        fact_semantics=EvidenceFactSemantics(
            attribute="work_location",
            cardinality=cardinality,
            semantic_scope=scope,
        ),
    )


def _context(*facts, enabled=True):
    return SimpleNamespace(
        tenant_id="tenant", user_id="user",
        authorized_sources=["memory"] if enabled else [],
        denied_sources=[], unresolved_sources=[],
        evidence=list(facts),
    )


def test_scoped_query_returns_only_matching_trusted_projection():
    context = _context(
        _fact("Detroit", project="42"),
        _fact("Chicago", project="99"),
        _fact("Boston", project=None, cardinality=FactCardinality.SINGLETON),
        _fact("Elsewhere", project="42", user="other"),
    )
    result = evaluate_personal_evidence(
        context, tenant_id="tenant", user_id="user",
        attribute="work_location", query_scope=(("project_id", "42"),),
    )
    assert result.status is EvidenceSufficiencyStatus.SUPPORTED
    assert result.value == "Detroit"

    decision = ExecutionDecision(
        intent="memory.recall",
        policy_constraints={
            "personal_evidence_attribute": "work_location",
            "personal_evidence_query_scope": {"project_id": "42"},
        },
    )
    decision.cognitive_context = context
    reply, metadata = ChatRuntime._grounded_personal_response(
        decision, tenant_id="tenant", user_id="user",
    )
    assert "project 42" in reply
    assert "Detroit" in reply
    assert all(value not in reply for value in ("Chicago", "Boston", "Elsewhere"))
    assert metadata["actual_provider"] is None


def test_unscoped_question_does_not_globalize_project_profile_fact():
    context = _context(_fact("Detroit", project="42"))
    result = evaluate_personal_evidence(
        context, tenant_id="tenant", user_id="user", attribute="work_location",
    )
    assert result.status is EvidenceSufficiencyStatus.AMBIGUOUS
    decision = ExecutionDecision(
        intent="memory.recall",
        policy_constraints={"personal_evidence_attribute": "work_location"},
    )
    decision.cognitive_context = context
    reply, _ = ChatRuntime._grounded_personal_response(
        decision, tenant_id="tenant", user_id="user",
    )
    assert "Detroit" not in reply


def test_invalid_or_mismatched_scope_never_uses_conversation_fallback():
    context = _context(_fact("Detroit", project="42"))
    decision = ExecutionDecision(
        intent="memory.recall",
        policy_constraints={
            "personal_evidence_attribute": "work_location",
            "personal_evidence_query_scope": {"project_id": "99"},
        },
    )
    decision.cognitive_context = context
    reply, meta = ChatRuntime._grounded_personal_response(
        decision, tenant_id="tenant", user_id="user",
    )
    assert "Detroit" not in reply
    assert meta["evidence_sufficiency"] != "supported"

    decision.policy_constraints["personal_evidence_query_scope"] = {"tenant_id": "other"}
    reply, meta = ChatRuntime._grounded_personal_response(
        decision, tenant_id="tenant", user_id="user",
    )
    assert "Detroit" not in reply
    assert meta["evidence_reason"] == "invalid_query_scope"


def test_historical_and_named_context_never_serve_current_values():
    context = _context(_fact("Detroit", project="42"))
    for issue in ("historical", "unresolved_scope"):
        decision = ExecutionDecision(
            intent="memory.recall",
            policy_constraints={
                "personal_evidence_attribute": "work_location",
                "personal_evidence_query_issue": issue,
            },
        )
        decision.cognitive_context = context
        reply, meta = ChatRuntime._grounded_personal_response(
            decision, tenant_id="tenant", user_id="user",
        )
        assert "Detroit" not in reply
        assert meta["evidence_sufficiency"] == "ambiguous"


def test_scope_cannot_override_runtime_policy_authorization():
    result = evaluate_personal_evidence(
        _context(_fact("Detroit", project="42"), enabled=False),
        tenant_id="tenant", user_id="user", attribute="work_location",
        query_scope=(("project_id", "42"),),
    )
    assert result.status is EvidenceSufficiencyStatus.MISSING
