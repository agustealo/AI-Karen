"""MI-06: favorite is an open-vocabulary relationship, not a list of nouns."""
from __future__ import annotations

import pytest

from ai_karen_engine.core.intelligence.preference_relation import (
    extract_favorite_assertion,
    requested_favorite_attribute,
)
from ai_karen_engine.core.intelligence.profile_attribute import requested_profile_attribute
from ai_karen_engine.core.memory.formation.evaluator import MemoryFormationEvaluator
from ai_karen_engine.core.memory.signals.semantic_classifier import (
    classify_explicit_user_memory, is_personal_memory_recall_query,
)
from ai_karen_engine.core.memory.signals.signal_models import ExtractionResult
from ai_karen_engine.core.memory.signals.signal_rules import RuleBasedExtractor


@pytest.mark.parametrize(("statement", "attribute", "value"), [
    ("My favorite color is green.", "favorite_color", "green"),
    ("Black is my favorite colour.", "favorite_color", "black"),
    ("My favourite music genre is reggae.", "favorite_music_genre", "reggae"),
    ("My fav film director is Ava DuVernay.", "favorite_film_director", "Ava DuVernay"),
    ("Bob Marley is my favorite reggae artist.", "favorite_reggae_artist", "Bob Marley"),
    ("My favorite quantum algorithm is Grover's algorithm.",
     "favorite_quantum_algorithm", "Grover's algorithm"),
    ("Actually orange is my favorite color now.", "favorite_color", "orange"),
    ("No! I just love black, it is my favorite color.", "favorite_color", "black"),
])
def test_unseen_favorite_domains_have_one_shared_semantics(statement, attribute, value):
    favorite = [
        s for s in classify_explicit_user_memory(statement)
        if s.signal_type == "preference" and s.metadata.get("attribute") == attribute
    ]
    assert len(favorite) == 1, statement
    signal = favorite[0]
    assert signal.metadata["normalized_value"] == value
    assert signal.metadata["assertion_modality"] == "asserted"
    assert signal.metadata["retention_scope"] == "user_profile"
    assert signal.metadata["explicit_user_statement"] is True


@pytest.mark.parametrize(("question", "attribute"), [
    ("What is my favorite color?", "favorite_color"),
    ("Whats my fav color?", "favorite_color"),
    ("what my fav color?", "favorite_color"),
    ("What's my favourite colour?", "favorite_color"),
    ("Who's my favorite film director?", "favorite_film_director"),
    ("What's my favorite music genre?", "favorite_music_genre"),
    ("What is my fav quantum algorithm?", "favorite_quantum_algorithm"),
    ("Do you remember my favorite food?", "favorite_food"),
])
def test_query_and_fact_share_one_attribute_owner(question, attribute):
    assert requested_favorite_attribute(question) == attribute
    assert requested_profile_attribute(question) == attribute
    assert is_personal_memory_recall_query(question)


@pytest.mark.parametrize("question", [
    "What is my favorite music genre and song?",
    "What is my favorite artist or band?",
    "What's your favorite artist?",
    "What is her favorite food?",
    "What is my favorite?",
    "What's my favorite genre and what's my favorite artist?",
])
def test_ambiguous_or_non_user_query_must_not_choose_a_fact(question):
    assert requested_favorite_attribute(question) is None


@pytest.mark.parametrize("statement", [
    "My friend's favorite artist is Bob Marley.",
    "She said my favorite artist is Bob Marley.",
    'She said "my favorite food is pizza".',
    '"My favorite color is green" is a quotation.',
    "My favorite genre is not reggae.",
    "Reggae is not my favorite genre.",
    "Explain the meaning of favorite music.",
    "My favorite music genre is none.",
    "I used to think my favorite genre is reggae.",
])
def test_third_person_quotes_negation_and_past_speculation_not_asserted(statement):
    assert extract_favorite_assertion(statement) is None
    assert not any(
        s.signal_type == "preference" and s.metadata.get("attribute", "").startswith("favorite_")
        for s in classify_explicit_user_memory(statement)
    )


@pytest.mark.parametrize(("statement", "attribute", "modality", "period"), [
    ("I love the color black, I think it's my favorite color.",
     "favorite_color", "uncertain", None),
    ("I think my favorite artist is Bob Marley.",
     "favorite_artist", "uncertain", None),
    ("I think reggae is my favorite genre.",
     "favorite_genre", "uncertain", None),
    ("My favorite song this week is Sunshine.",
     "favorite_song", "asserted", "this week"),
    ("My favorite meal today is breakfast.",
     "favorite_meal", "asserted", "today"),
])
def test_tentative_and_time_bounded_facts_are_not_unrestricted_ltm(
    statement, attribute, modality, period,
):
    facts = [
        s for s in classify_explicit_user_memory(statement)
        if s.signal_type == "preference" and s.metadata.get("attribute") == attribute
    ]
    assert len(facts) == 1, statement
    meta = facts[0].metadata
    assert meta["assertion_modality"] == modality
    assert meta["retention_scope"] == "session"
    assert meta["temporal_scope"] == period


class _SingleSignalPipeline:
    def __init__(self, signals):
        self.signals = signals

    async def process_text(self, **_):
        return ExtractionResult(signals=self.signals)


class _NoPII:
    def extract_safe_metadata(self, value):
        return {"contains_pii": False, "pii_types": []}


class _FailOnSalience:
    async def evaluate(self, *_args):
        raise AssertionError("explicit user candidates must not need a salience model")


@pytest.mark.asyncio
async def test_formation_admits_asserted_open_domain_but_not_uncertain_or_temporary():
    statements = (
        ("My favorite music genre is reggae.", 1),
        ("My favorite song this week is Sunshine.", 0),
        ("I think my favorite genre is reggae.", 0),
    )
    for statement, expected in statements:
        signals = classify_explicit_user_memory(statement)
        evaluator = MemoryFormationEvaluator(
            signal_pipeline=_SingleSignalPipeline(signals),
            worthiness_scorer=_FailOnSalience(),
            privacy_classifier=_NoPII(),
        )
        result = await evaluator.evaluate(
            text=statement, tenant_id="tenant-1", user_id="user-1",
        )
        assert result.admitted_count == expected, statement


def test_fallback_never_duplicates_a_favorite_as_weak_generic_preference():
    signals = RuleBasedExtractor().extract(
        "I love the color black, I think it's my favorite color."
    )
    assert len([s for s in signals if s.signal_type == "preference"]) == 1
    assert signals[0].metadata["retention_scope"] == "session"


def test_corrected_favorite_marks_intent_but_keeps_single_attribute_identity():
    before = extract_favorite_assertion("My favorite genre is reggae.")
    after = extract_favorite_assertion("Actually my favorite genre is dancehall now.")
    assert before is not None and after is not None
    assert before.attribute == after.attribute == "favorite_genre"
    assert not before.explicit_correction
    assert after.explicit_correction


@pytest.mark.asyncio
async def test_sensitive_favorites_are_not_automatically_saved():
    for statement in (
        "My favorite password is hunter2.",
        "My favorite medical diagnosis is something private.",
        "My favorite political party is something private.",
    ):
        evaluator = MemoryFormationEvaluator(
            signal_pipeline=_SingleSignalPipeline(
                classify_explicit_user_memory(statement)
            ),
            worthiness_scorer=_FailOnSalience(),
            privacy_classifier=_NoPII(),
        )
        result = await evaluator.evaluate(
            text=statement, tenant_id="tenant-1", user_id="user-1",
        )
        assert result.admitted_count == 0, statement


@pytest.mark.asyncio
async def test_person_names_in_ordinary_artist_preferences_can_be_confidential():
    class _NameOnlyPII:
        def extract_safe_metadata(self, value):
            return {"contains_pii": True, "pii_types": ["name"]}

    statement = "My favorite film director is Ava DuVernay."
    evaluator = MemoryFormationEvaluator(
        signal_pipeline=_SingleSignalPipeline(classify_explicit_user_memory(statement)),
        worthiness_scorer=_FailOnSalience(),
        privacy_classifier=_NameOnlyPII(),
    )
    result = await evaluator.evaluate(
        text=statement, tenant_id="tenant-1", user_id="user-1",
    )
    assert result.admitted_count == 1
    assert result.admitted[0].signal.metadata["sensitivity_class"] == "confidential"


def test_negated_favorite_with_discourse_marker_is_not_asserted():
    for statement in (
        "My favorite genre is no longer reggae.",
        "My favorite genre is never jazz.",
        "My favorite color is not green.",
    ):
        assert extract_favorite_assertion(statement) is None
