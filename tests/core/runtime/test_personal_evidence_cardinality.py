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


def check(ctx, *, cardinality=FactCardinality.SINGLETON):
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
