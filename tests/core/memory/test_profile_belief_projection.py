"""MI-07: the same belief policy owns typed assertions and PostgreSQL slots."""
from __future__ import annotations

from dataclasses import replace

import pytest

from ai_karen_engine.core.memory.belief_resolution import (
    ProfileProjectionEvidence,
    resolve_profile_projection,
    is_trusted_profile_correction,
)
from ai_karen_engine.core.memory.semantic_contract import (
    AssertionModality, FactCardinality, MemoryOperation,
    merge_memory_metadata,
)


def observation(value="black", *, event="e1", tenant="t", user="u",
                slot="favorite_color", cardinality=FactCardinality.SINGLETON,
                modality=AssertionModality.ASSERTED):
    return ProfileProjectionEvidence(
        tenant_id=tenant, user_id=user, fact_key=slot,
        value=value, source_event_id=event, cardinality=cardinality,
        modality=modality,
    )


def test_new_fact_is_created():
    result = resolve_profile_projection(observation(), ())
    assert result.operation is MemoryOperation.CREATE


def test_duplicate_value_reinforces_without_changing_belief():
    result = resolve_profile_projection(
        observation(event="e2"), (observation(),)
    )
    assert result.operation is MemoryOperation.REINFORCE
    assert result.source_event_ids == ("e2", "e1")


def test_different_value_cannot_silently_replace_current_memory():
    before = observation()
    after = observation("green", event="e2")
    resolution = resolve_profile_projection(after, (before,))
    assert resolution.operation is MemoryOperation.QUARANTINE
    assert before.value == "black"
    assert resolution.affected_fact_keys == ()


def test_explicit_correction_supersedes_same_slot_only():
    old = observation()
    new = observation("green", event="e2")
    resolution = resolve_profile_projection(
        new, (old,), explicit_correction=True,
    )
    assert resolution.operation is MemoryOperation.SUPERSEDE
    assert resolution.affected_fact_keys == ("favorite_color",)


def test_disjoint_favorite_categories_can_coexist():
    old = observation(slot="favorite_artist")
    new = observation("reggae", event="e2", slot="favorite_genre")
    assert resolve_profile_projection(new, ()).operation is MemoryOperation.CREATE
    with pytest.raises(ValueError, match="verified slot"):
        resolve_profile_projection(new, (old,))


def test_set_members_dont_clobber_each_other():
    old = observation("Bob Marley", slot="favorite_artist",
                      cardinality=FactCardinality.SET)
    new = observation("Nina Simone", event="e2", slot="favorite_artist:nina",
                      cardinality=FactCardinality.SET)
    assert resolve_profile_projection(new, ()).operation is MemoryOperation.CREATE
    assert resolve_profile_projection(
        replace(old, source_event_id="e2"), (old,),
    ).operation is MemoryOperation.REINFORCE


@pytest.mark.parametrize("modality", [
    AssertionModality.UNCERTAIN, AssertionModality.NEGATED,
    AssertionModality.QUOTED, AssertionModality.HYPOTHETICAL,
    AssertionModality.INFERRED,
])
def test_nonassertions_never_modify_current_profile(modality):
    assert resolve_profile_projection(
        observation("green", event="e2", modality=modality),
        (observation(),), explicit_correction=True,
    ).operation is MemoryOperation.QUARANTINE


@pytest.mark.parametrize(("tenant", "user"), [("other", "u"), ("t", "other")])
def test_scope_mismatch_is_rejected(tenant, user):
    with pytest.raises(ValueError, match="cross-scope"):
        resolve_profile_projection(
            observation("green", event="e2", tenant=tenant, user=user),
            (observation(),), explicit_correction=True,
        )


def test_runtime_cannot_forge_correction_modality_or_domain():
    for key, value in (
        ("explicit_correction", True), ("assertion_modality", "asserted"),
        ("preference_domain", "music"), ("temporal_scope", "this week"),
    ):
        with pytest.raises(ValueError, match="untrusted semantic"):
            merge_memory_metadata(
                signal_metadata={"attribute": "favorite_genre"},
                runtime_metadata={key: value},
            )


def test_matching_signed_semantics_cannot_be_replaced_by_transport():
    with pytest.raises(ValueError, match="conflicting semantic"):
        merge_memory_metadata(
            signal_metadata={"explicit_correction": False},
            runtime_metadata={"explicit_correction": True},
        )


@pytest.mark.parametrize(
    ("source_type", "classifier", "explicit", "expected"),
    [
        ("chat_user", "explicit_semantic_rule", True, True),
        ("chat", "explicit_general_fact_rule", True, True),
        ("chat_user", "explicit_semantic_rule", False, False),
        ("profile_correction", "explicit_semantic_rule", False, True),
        ("profile_correction", "explicit_general_fact_rule", False, True),
        ("profile_correction", "llm_guess", True, False),
        ("profile_correction", "explicit_general_fact_rule", False, False),
        ("system", "explicit_semantic_rule", True, False),
    ],
)
def test_correction_provenance_requires_classified_user_evidence(
    source_type, classifier, explicit, expected,
):
    evidence = {
        "source": classifier,
        "explicit_user_statement": True,
        "explicit_correction": explicit,
    }
    if source_type == "profile_correction" and classifier == "explicit_general_fact_rule" and not expected:
        evidence["explicit_user_statement"] = False
    assert is_trusted_profile_correction(
        source_type=source_type,
        signal_metadata=evidence,
        merged_metadata=evidence,
    ) is expected


def test_runtime_supplied_correction_flag_is_not_authority():
    assert not is_trusted_profile_correction(
        source_type="chat_user",
        signal_metadata={
            "source": "explicit_general_fact_rule",
            "explicit_user_statement": True,
        },
        merged_metadata={"explicit_correction": True},
    )


@pytest.mark.parametrize(
    ("utterance", "signal_type", "attribute", "expected"),
    [
        ("Actually my name is Alex.", "identity_fact", "preferred_name", True),
        ("Correction: I work at Ford.", "profile_fact", "employer", True),
        ("To correct myself, I live in Detroit.", "profile_fact", "residence_location", True),
        ("My name is Alex.", "identity_fact", "preferred_name", False),
        ("I work at Ford.", "profile_fact", "employer", False),
    ],
)
def test_domain_neutral_self_correction_governs_classified_claims(
    utterance, signal_type, attribute, expected,
):
    from ai_karen_engine.core.memory.signals.semantic_classifier import (
        classify_explicit_user_memory,
    )

    signals = [
        candidate
        for candidate in classify_explicit_user_memory(utterance)
        if candidate.signal_type == signal_type
        and candidate.metadata.get("attribute") == attribute
    ]
    assert len(signals) == 1
    assert (signals[0].metadata.get("explicit_correction") is True) is expected


@pytest.mark.parametrize(
    "utterance",
    [
        "Actually she said my name is Alex.",
        "I was wrong about what someone else said.",
        "Correction: they work at Ford.",
        "Actually, what is my employer?",
        "My favorite genre is reggae.",
    ],
)
def test_correction_grammar_never_grants_authority_to_ambiguous_discourse(utterance):
    from ai_karen_engine.core.intelligence.correction_intent import (
        is_explicit_self_correction,
    )

    assert not is_explicit_self_correction(utterance)
