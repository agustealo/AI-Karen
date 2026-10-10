"""Meaning-preserving normalization for bounded personal recall interpretation."""
import pytest

from ai_karen_engine.core.intelligence.profile_attribute import (
    normalize_personal_query, requested_profile_attribute,
)
from ai_karen_engine.core.memory.signals.semantic_classifier import (
    is_personal_memory_recall_query,
    is_explicit_memory_save_request,
)


@pytest.mark.parametrize(
    ("plain", "emphatic", "attribute"),
    [
        ("What is my name?", "What is my fucking name?!", "preferred_name"),
        ("What's my name?", "What's my freaking name?", "preferred_name"),
        ("Where am I from?", "Where the fuck am I from?", "origin_location"),
        ("Where was I born?", "Where the hell was I born?", "birthplace"),
        ("Where do I live?", "Where do I damn live?", "residence_location"),
        ("Where do I work?", "Where the fuck do I work?", "work_location"),
    ],
)
def test_emphasis_cannot_change_personal_recall_intent(plain, emphatic, attribute):
    assert is_personal_memory_recall_query(plain)
    assert is_personal_memory_recall_query(emphatic)
    assert requested_profile_attribute(plain) == attribute
    assert requested_profile_attribute(emphatic) == attribute


def test_normalization_does_not_invent_recall_or_change_save_requests():
    assert normalize_personal_query("What is my fucking name?") == "what is my name?"
    assert not is_personal_memory_recall_query("Tell me a fucking story")
    assert not is_personal_memory_recall_query("What is my account password?")
    assert not is_explicit_memory_save_request("What is my fucking name?")
    assert is_explicit_memory_save_request("Remember my name.")
