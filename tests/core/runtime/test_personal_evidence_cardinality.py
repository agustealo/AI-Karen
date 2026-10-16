"""Cardinality-aware sufficiency preserves authorization and scalar safety."""

from types import SimpleNamespace

from ai_karen_engine.core.context.contracts import (
    EvidenceContradiction,
    EvidenceContradictionStatus,
    EvidenceScope,
    EvidenceSource,
    EvidenceTemporalContext,
)
from ai_karen_engine.core.memory.semantic_contract import FactCardinality
from ai_karen_engine.core.runtime.evidence_sufficiency import (
    EvidenceSufficiencyStatus,
    evaluate_personal_evidence,
)


def evidence(value: str, *, user="u1", contradiction=EvidenceContradictionStatus.NONE):
    return SimpleNamespace(
        source=EvidenceSource.MEMORY,
        scope=EvidenceScope(tenant_id="t1", user_id=user),
        content=f"favorite_artist: {value}",
        evidence_id=f"e-{value}",
        temporal=EvidenceTemporalContext(),
        contradiction=EvidenceContradiction(status=contradiction),
    )


def context(*items, authorized=True):
    return SimpleNamespace(
        tenant_id="t1",
        user_id="u1",
        authorized_sources=["memory"] if authorized else [],
        denied_sources=[],
        unresolved_sources=[],
        evidence=list(items),
    )


def check(ctx, *, cardinality=None):
    return evaluate_personal_evidence(
        ctx, tenant_id="t1", user_id="u1",
        attribute="favorite_artist", cardinality=cardinality,
    )


def test_scalar_values_still_conflict():
    result = check(context(evidence("Bob Marley"), evidence("Nina Simone")))
    assert result.status is EvidenceSufficiencyStatus.CONTRADICTORY
    assert not result.may_assert


def test_set_values_coexist_without_invented_singleton():
    result = check(
        context(evidence("Bob Marley"), evidence("Nina Simone")),
        cardinality=FactCardinality.SET,
    )
    assert result.status is EvidenceSufficiencyStatus.SUPPORTED_SET
    assert result.values == ("Bob Marley", "Nina Simone")
    assert result.value is None
    assert result.may_assert


def test_set_member_duplicates_are_deduplicated():
    result = check(context(evidence("Bob Marley"), evidence("bob marley")),
                   cardinality=FactCardinality.SET)
    assert result.values == ("Bob Marley",)


def test_cross_user_evidence_not_eligible():
    result = check(context(evidence("Bob Marley", user="u2")),
                   cardinality=FactCardinality.SET)
    assert result.status is EvidenceSufficiencyStatus.MISSING


def test_denied_recall_never_uses_set_values():
    result = check(context(evidence("Bob Marley"), authorized=False),
                   cardinality=FactCardinality.SET)
    assert result.status is EvidenceSufficiencyStatus.MISSING


def test_confirmed_conflict_blocks_set_answer():
    result = check(context(evidence("Bob Marley", contradiction=EvidenceContradictionStatus.CONFIRMED)),
                   cardinality=FactCardinality.SET)
    assert result.status is EvidenceSufficiencyStatus.CONTRADICTORY
    assert not result.may_assert


def trusted_set(value: str, *, scope=(("domain", "music"),)):
    from ai_karen_engine.core.context.contracts import EvidenceFactSemantics

    item = evidence(value)
    item.fact_semantics = EvidenceFactSemantics(
        attribute="favorite_artist",
        cardinality=FactCardinality.SET,
        semantic_scope=scope,
    )
    return item


def test_runtime_auto_uses_verified_projected_set_cardinality():
    result = check(context(trusted_set("Bob Marley"), trusted_set("Nina Simone")))
    assert result.status is EvidenceSufficiencyStatus.SUPPORTED_SET
    assert result.values == ("Bob Marley", "Nina Simone")
    assert result.value is None


def test_runtime_fails_closed_on_mixed_or_missing_projected_semantics():
    first = trusted_set("Bob Marley")
    second = evidence("Nina Simone")
    for candidate in (second,):
        result = check(context(first, candidate))
        assert result.status is EvidenceSufficiencyStatus.AMBIGUOUS
        assert result.reason == "mixed_or_unverified_profile_semantics"


def test_runtime_does_not_merge_distinct_context_scopes():
    result = check(context(
        trusted_set("Bob Marley", scope=(("genre", "reggae"),)),
        trusted_set("Nina Simone", scope=(("genre", "jazz"),)),
    ))
    assert result.status is EvidenceSufficiencyStatus.AMBIGUOUS
    assert not result.may_assert


def test_arbitrary_model_metadata_cannot_turn_singleton_conflict_into_set():
    first, second = evidence("Bob Marley"), evidence("Nina Simone")
    first.metadata = {"cardinality": "set", "memory_metadata": {"cardinality": "set"}}
    second.metadata = {"cardinality": "set"}
    result = check(context(first, second))
    assert result.status is EvidenceSufficiencyStatus.CONTRADICTORY


def test_grounded_response_renders_all_verified_set_members_without_provider():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
    from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision

    decision = ExecutionDecision(
        intent="memory.recall",
        policy_constraints={"personal_evidence_attribute": "favorite_artist"},
    )
    decision.cognitive_context = context(
        trusted_set("Bob Marley"), trusted_set("Nina Simone"),
    )
    answer, metadata = ChatRuntime._grounded_personal_response(
        decision, tenant_id="t1", user_id="u1",
    )
    assert "Bob Marley" in answer
    assert "Nina Simone" in answer
    assert metadata["evidence_sufficiency"] == "supported_set"
    assert metadata["evidence_cardinality"] == "set"
    assert metadata["evidence_value_count"] == 2
    assert metadata["response_source"] == "authorized_memory_evidence"
    assert metadata["actual_provider"] is None


def test_scoped_singleton_is_not_projected_into_global_personal_truth():
    from ai_karen_engine.core.context.contracts import EvidenceFactSemantics
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
    from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision

    scoped = evidence("Detroit")
    scoped.content = "work_location: Detroit"
    scoped.fact_semantics = EvidenceFactSemantics(
        attribute="work_location",
        cardinality=FactCardinality.SCOPED_SINGLETON,
        semantic_scope=(("project_id", "42"),),
    )
    matched = context(scoped)
    result = evaluate_personal_evidence(
        matched, tenant_id="t1", user_id="u1", attribute="work_location",
    )
    assert result.status is EvidenceSufficiencyStatus.AMBIGUOUS
    assert result.reason == "scoped_fact_requires_query_scope"

    decision = ExecutionDecision(
        intent="memory.recall",
        policy_constraints={"personal_evidence_attribute": "work_location"},
    )
    decision.cognitive_context = matched
    answer, metadata = ChatRuntime._grounded_personal_response(
        decision, tenant_id="t1", user_id="u1",
    )
    assert "Detroit" not in answer
    assert metadata["evidence_sufficiency"] == "ambiguous"


def test_project_scoped_set_is_not_generalized_into_a_global_favorite():
    scoped = trusted_set("Bob Marley", scope=(("project_id", "42"),))
    result = check(context(scoped))
    assert result.status is EvidenceSufficiencyStatus.AMBIGUOUS
    assert result.reason == "scoped_fact_requires_query_scope"


def test_saved_set_agrees_with_multiple_authenticated_conversation_members():
    from ai_karen_engine.core.context.contracts import (
        ContextEvidence, ContextRequirements, EvidenceScope,
    )
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
    from ai_karen_engine.core.runtime.evidence_sufficiency import (
        evaluate_conversation_personal_evidence,
    )
    from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision

    evidence_items = [
        trusted_set("Bob Marley"),
        trusted_set("Nina Simone"),
        ContextEvidence(
            evidence_id="u1",
            source=EvidenceSource.CONVERSATION,
            content="My favorite artist is Bob Marley.",
            scope=EvidenceScope(tenant_id="t1", user_id="u1", conversation_id="c1"),
            metadata={"role": "user"},
        ),
        ContextEvidence(
            evidence_id="u2",
            source=EvidenceSource.CONVERSATION,
            content="My favorite artist is Nina Simone.",
            scope=EvidenceScope(tenant_id="t1", user_id="u1", conversation_id="c1"),
            metadata={"role": "user"},
        ),
    ]
    ctx = context(*evidence_items)
    ctx.requirements = ContextRequirements(
        request_id="req", correlation_id="corr", tenant_id="t1",
        user_id="u1", conversation_id="c1",
    )
    ctx.authorized_sources = ["memory", "conversation"]
    assert evaluate_conversation_personal_evidence(
        ctx, tenant_id="t1", user_id="u1", attribute="favorite_artist",
    ).status is EvidenceSufficiencyStatus.CONTRADICTORY

    decision = ExecutionDecision(
        intent="memory.recall",
        policy_constraints={"personal_evidence_attribute": "favorite_artist"},
    )
    decision.cognitive_context = ctx
    answer, meta = ChatRuntime._grounded_personal_response(
        decision, tenant_id="t1", user_id="u1",
    )
    assert "Bob Marley" in answer and "Nina Simone" in answer
    assert meta["evidence_sufficiency"] == "supported_set"
    assert meta["response_source"] == "authorized_memory_evidence"

    # A new claim outside the saved SET needs reconciliation, not acceptance.
    evidence_items[-1].content = "My favorite artist is Prince."
    answer, meta = ChatRuntime._grounded_personal_response(
        decision, tenant_id="t1", user_id="u1",
    )
    assert "Prince" not in answer
    assert meta["evidence_sufficiency"] == "ambiguous"
    assert meta["evidence_reason"] == "saved_set_and_conversation_need_reconciliation"

    # Even a correction to an existing member might narrow or replace the
    # collection; do not serve old SET contents as current truth.
    evidence_items[-1].content = "Actually my favorite artist is Bob Marley."
    answer, meta = ChatRuntime._grounded_personal_response(
        decision, tenant_id="t1", user_id="u1",
    )
    assert "Nina Simone" not in answer
    assert meta["evidence_sufficiency"] == "ambiguous"
    assert meta["evidence_reason"] == "set_correction_requires_reconciliation"
