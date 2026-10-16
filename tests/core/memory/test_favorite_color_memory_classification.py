"""Explicit user preference statements must not be reinterpreted as identity."""
import pytest

from ai_karen_engine.core.memory.signals.semantic_classifier import (
    classify_explicit_user_memory,
)


@pytest.mark.parametrize("utterance", [
    "I love the color black, I think its my favorite color",
    "I love the color black, I think it's my favorite color",
    "no! I just love black, it is my favorite color.",
    "My favorite color is black.",
    "Black is my favorite color.",
])
def test_favorite_color_conversation_is_typed_preference(utterance: str) -> None:
    signals = classify_explicit_user_memory(utterance)
    favorites = [
        s for s in signals
        if s.signal_type == "preference"
        and s.metadata.get("attribute") == "favorite_color"
    ]
    assert len(favorites) == 1
    assert favorites[0].metadata["normalized_value"] == "black"
    uncertain = "I think" in utterance
    assert favorites[0].metadata["retention_scope"] == (
        "session" if uncertain else "user_profile"
    )
    assert favorites[0].metadata["assertion_modality"] == (
        "uncertain" if uncertain else "asserted"
    )
    assert favorites[0].metadata["semantic_class"] == "preference"
    assert not any(s.metadata.get("semantic_class") == "race" for s in signals)


def test_liking_black_without_favorite_claim_does_not_invent_favorite() -> None:
    signals = classify_explicit_user_memory("I love the color black.")
    assert not any(s.metadata.get("attribute") == "favorite_color" for s in signals)

@pytest.mark.parametrize("question", [
    "Whats my fav color?",
    "what my fav color?",
    "What's my favorite color?",
    "What is my favourite colour?",
    "Which is my favorite color?",
])
def test_favorite_color_questions_route_to_explicit_profile_attribute(question: str) -> None:
    from ai_karen_engine.core.intelligence.profile_attribute import (
        requested_profile_attribute,
    )
    from ai_karen_engine.core.memory.signals.semantic_classifier import (
        is_personal_memory_recall_query,
    )

    assert requested_profile_attribute(question) == "favorite_color"
    assert is_personal_memory_recall_query(question)


@pytest.mark.parametrize("question", [
    "Who am I?",
    "What is my name?",
    "What is my favorite food?",
])
def test_non_color_questions_do_not_route_to_color(question: str) -> None:
    from ai_karen_engine.core.intelligence.profile_attribute import (
        requested_profile_attribute,
    )

    assert requested_profile_attribute(question) != "favorite_color"

