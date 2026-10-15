"""Adversarial invariants for memory semantic contract v1."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from ai_karen_engine.core.memory.semantic_contract import (
    AssertionModality,
    FactCardinality,
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


def assertion(*, value="Bob Marley", domain="music", facet="reggae",
              cardinality=FactCardinality.SCOPED_SINGLETON,
              subject=None, user_id="user-1", modality=AssertionModality.ASSERTED):
    return SemanticAssertion(
        tenant_id="tenant-1",
        user_id=user_id,
        subject=subject or SemanticSubject(kind=SubjectKind.SELF),
        predicate=SemanticPredicate(namespace="preference", relation="favorite_artist"),
        object=SemanticObject(type="artist", canonical_value=value),
        qualifiers=SemanticQualifiers(domain=domain, facet=facet),
        temporality=SemanticTemporality(observed_at=datetime.now(timezone.utc)),
        modality=modality,
        confidence=SemanticConfidence(extraction=0.9, assertion=0.85, source_trust=1.0),
        cardinality=cardinality,
        provenance=SemanticProvenance(
            source_event_id="event-1", source_message_id="msg-1",
            source_origin="chat_user", speaker="user",
            evidence_text="Bob Marley", evidence_span_start=0,
            evidence_span_end=10, extractor="test", extractor_version="1",
        ),
    )


def test_scoped_favorites_have_distinct_identity() -> None:
    reggae = assertion()
    jazz = assertion(value="Nina Simone", facet="jazz")
    assert reggae.fact_key != jazz.fact_key


def test_singleton_values_reuse_identity_for_governed_supersession() -> None:
    black = assertion(value="black", domain="color", facet="general",
                      cardinality=FactCardinality.SINGLETON)
    green = replace(black, object=SemanticObject(type="artist", canonical_value="green"))
    assert black.fact_key == green.fact_key


def test_set_members_coexist_and_equivalent_member_reuses_identity() -> None:
    first = assertion(cardinality=FactCardinality.SET)
    second = replace(first, object=SemanticObject(type="artist", canonical_value="Nina Simone"))
    duplicate = replace(first, object=SemanticObject(type="artist", canonical_value="bob marley"))
    assert first.fact_key != second.fact_key
    assert first.fact_key == duplicate.fact_key


def test_user_and_tenant_isolation_are_in_identity() -> None:
    fact = assertion()
    assert fact.fact_key != replace(fact, user_id="user-2").fact_key
    assert fact.fact_key != replace(fact, tenant_id="tenant-2").fact_key


def test_third_party_cannot_masquerade_as_self() -> None:
    with pytest.raises(ValueError, match="non-self"):
        SemanticSubject(kind=SubjectKind.OTHER_PERSON)
    with pytest.raises(ValueError, match="self subject"):
        assertion(subject=SemanticSubject(kind=SubjectKind.SELF, entity_id="other-person"))


def test_invalid_evidence_span_rejected() -> None:
    fact = assertion()
    with pytest.raises(ValueError, match="evidence span"):
        replace(fact, provenance=replace(fact.provenance, evidence_span_end=9))


def test_naive_time_and_invalid_confidence_rejected() -> None:
    fact = assertion()
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(fact, temporality=SemanticTemporality(observed_at=datetime(2026, 10, 15)))
    with pytest.raises(ValueError, match="\[0, 1\]"):
        SemanticConfidence(extraction=1.2, assertion=0.7, source_trust=1.0)


def test_unknown_semantic_extensions_rejected() -> None:
    with pytest.raises(ValueError, match="extensions"):
        replace(assertion(), extension={"permission_override": True})


def test_assertion_is_a_frozen_data_contract() -> None:
    fact = assertion()
    with pytest.raises((AttributeError, TypeError)):
        fact.user_id = "different"


def test_temporal_event_identity_tracks_source_event() -> None:
    fact = assertion(cardinality=FactCardinality.EVENT)
    different_event = replace(
        fact, provenance=replace(fact.provenance, source_event_id="event-2")
    )
    assert fact.fact_key != different_event.fact_key


def test_hypothetical_remains_hypothetical() -> None:
    fact = assertion(modality=AssertionModality.HYPOTHETICAL)
    assert fact.modality is AssertionModality.HYPOTHETICAL
