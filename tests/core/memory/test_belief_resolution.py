"""Adversarial belief state resolution cases for immutable semantic evidence."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from ai_karen_engine.core.memory.belief_resolution import (
    BeliefResolutionReason,
    ProfileBeliefEvidence,
    resolve_belief,
)
from ai_karen_engine.core.memory.semantic_contract import (
    AssertionModality,
    FactCardinality,
    MemoryOperation,
    SemanticAssertion,
    SemanticConfidence,
    SemanticObject,
    SemanticPredicate,
    SemanticProvenance,
    SemanticQualifiers,
    SemanticSubject,
    SemanticTemporality,
    SubjectKind,
)


def fact(value="black", *, domain="color", facet="general",
         cardinality=FactCardinality.SCOPED_SINGLETON, event="e1"):
    return SemanticAssertion(
        tenant_id="tenant", user_id="user",
        subject=SemanticSubject(kind=SubjectKind.SELF),
        predicate=SemanticPredicate(namespace="preference", relation="favorite"),
        object=SemanticObject(type="string", canonical_value=value),
        qualifiers=SemanticQualifiers(domain=domain, facet=facet),
        temporality=SemanticTemporality(observed_at=datetime.now(timezone.utc)),
        modality=AssertionModality.ASSERTED,
        confidence=SemanticConfidence(extraction=1.0, assertion=0.9, source_trust=1.0),
        cardinality=cardinality,
        provenance=SemanticProvenance(
            source_event_id=event, source_message_id=event, source_origin="chat_user",
            speaker="user", evidence_text=value, evidence_span_start=0,
            evidence_span_end=len(value), extractor="deterministic", extractor_version="1",
        ),
    )


def test_new_fact_creates_new_state():
    result = resolve_belief(fact(), ())
    assert result.operation is MemoryOperation.CREATE
    assert result.reason is BeliefResolutionReason.NEW_IDENTITY


def test_repeated_statement_reinforces_without_replacing_event():
    result = resolve_belief(fact(event="e2"), (fact(),))
    assert result.operation is MemoryOperation.REINFORCE
    assert result.source_event_ids == ("e2", "e1")


def test_contextual_favorites_coexist_without_supersession():
    old = fact(value="Bob Marley", domain="music", facet="reggae")
    new = fact(value="Nina Simone", domain="music", facet="jazz", event="e2")
    result = resolve_belief(new, (old,))
    assert result.operation is MemoryOperation.CREATE
    assert result.reason is BeliefResolutionReason.DISTINCT_CONTEXT


def test_multi_valued_favorites_coexist():
    first = fact("Bob Marley", domain="music", cardinality=FactCardinality.SET)
    second = fact("Nina Simone", domain="music", cardinality=FactCardinality.SET, event="e2")
    result = resolve_belief(second, (first,))
    assert result.operation is MemoryOperation.CREATE
    assert result.reason is BeliefResolutionReason.COEXISTING_MEMBER


def test_singleton_conflict_requires_explicit_correction():
    original = fact()
    new = fact("green", event="e2")
    unconfirmed = resolve_belief(new, (original,))
    assert unconfirmed.operation is MemoryOperation.QUARANTINE
    assert unconfirmed.reason is BeliefResolutionReason.UNRESOLVED_CONFLICT
    corrected = resolve_belief(new, (original,), explicit_correction=True)
    assert corrected.operation is MemoryOperation.SUPERSEDE
    assert corrected.affected_fact_keys == (original.fact_key,)


@pytest.mark.parametrize("modality", [
    AssertionModality.HYPOTHETICAL, AssertionModality.INFERRED,
    AssertionModality.QUOTED, AssertionModality.UNCERTAIN,
])
def test_non_asserted_information_never_automatically_changes_belief(modality):
    candidate = replace(fact(), modality=modality)
    assert resolve_belief(candidate, ()).operation is MemoryOperation.QUARANTINE


def test_cross_tenant_data_is_never_compared():
    current = fact()
    incoming = replace(current, tenant_id="different")
    with pytest.raises(ValueError, match="cross-scope"):
        resolve_belief(incoming, (current,))


def test_event_assertions_are_individually_identified():
    prior = fact(cardinality=FactCardinality.EVENT)
    later = fact(cardinality=FactCardinality.EVENT, event="e2")
    assert resolve_belief(later, (prior,)).operation is MemoryOperation.CREATE


def test_input_assertions_remain_unchanged():
    previous = fact()
    new = fact("green", event="e2")
    before = previous.fact_key
    resolve_belief(new, (previous,), explicit_correction=True)
    assert previous.fact_key == before
    assert previous.object.canonical_value == "black"


def projected(value="black", *, event="event-1", key="slot", tenant="tenant",
              category="preference", attribute="favorite_color",
              scope='{"cardinality":"singleton","qualifiers":{}}',
              modality=AssertionModality.ASSERTED,
              cardinality=FactCardinality.SINGLETON):
    return ProfileBeliefEvidence(
        tenant_id=tenant, user_id="user", category=category,
        attribute=attribute, projection_key=key, scope_key=scope,
        source_event_id=event, value=value, cardinality=cardinality,
        modality=modality,
    )


def test_projected_profile_reinforces_without_fabricating_semantic_provenance():
    current = projected()
    repeated = projected("BLACK", event="event-2")
    result = resolve_belief(repeated, (current,))
    assert result.operation is MemoryOperation.REINFORCE
    assert result.source_event_ids == ("event-2", "event-1")


def test_profile_correction_vs_unresolved_disagreement_uses_shared_resolver():
    first = projected()
    changed = projected("green", event="event-2")
    unconfirmed = resolve_belief(changed, (first,))
    assert unconfirmed.operation is MemoryOperation.QUARANTINE
    confirmed = resolve_belief(changed, (first,), explicit_correction=True)
    assert confirmed.operation is MemoryOperation.SUPERSEDE
    assert confirmed.affected_fact_keys == ("slot",)


def test_profile_set_members_and_contexts_remain_distinct():
    a = projected("Bob Marley", event="e1", key="member-a",
                  cardinality=FactCardinality.SET,
                  scope='{"cardinality":"set","qualifiers":{"domain":"music"}}')
    b = projected("Nina Simone", event="e2", key="member-b",
                  cardinality=FactCardinality.SET,
                  scope=a.scope_key)
    result = resolve_belief(b, (a,))
    assert result.operation is MemoryOperation.CREATE
    assert result.reason is BeliefResolutionReason.COEXISTING_MEMBER
    distinct = projected("jazz", event="e3", key="another-scope")
    assert resolve_belief(distinct, (a,)).operation is MemoryOperation.CREATE


def test_profile_nonassertion_and_cross_scope_are_rejected():
    prior = projected()
    uncertain = projected("green", event="event-2",
                          modality=AssertionModality.UNCERTAIN)
    assert resolve_belief(
        uncertain, (prior,), explicit_correction=True,
    ).operation is MemoryOperation.QUARANTINE
    with pytest.raises(ValueError, match="cross-scope"):
        resolve_belief(projected("green", tenant="other"), (prior,))
