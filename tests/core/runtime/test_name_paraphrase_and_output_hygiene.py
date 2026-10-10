"""Name recall uses intent, not exact phrasings or speech filtering."""

import pytest

from ai_karen_engine.core.intelligence.profile_attribute import requested_profile_attribute
from ai_karen_engine.core.memory.signals.semantic_classifier import is_personal_memory_recall_query
from ai_karen_engine.core.errors.response_validation import validate_response_text


@pytest.mark.parametrize("utterance", [
    "Whats my name?",
    "Whats my fucking name?",
    "My name is what?",
    "What am I called?",
    "What do people call me?",
    "I am who, what am I called?",
])
def test_name_variants_retrieve_the_same_requested_attribute(utterance):
    assert requested_profile_attribute(utterance) == "preferred_name"
    assert is_personal_memory_recall_query(utterance)


@pytest.mark.parametrize("utterance", [
    "My name is Zeus.",
    "Who is Zeus personally?",
    "Tell me a fucking story.",
])
def test_other_utterances_do_not_become_name_recall(utterance):
    assert requested_profile_attribute(utterance) is None


@pytest.mark.parametrize("output", [
    "Karen responds to the user's question about their name by repeating their preferred name.",
    "To determine who 'I am' and what my name is, we can analyze several factors:",
])
def test_model_self_narration_is_rejected(output):
    assert not validate_response_text(output)


def test_profane_direct_reply_is_not_censored():
    assert validate_response_text("Your fucking name is Zeus.")
