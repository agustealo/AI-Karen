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
