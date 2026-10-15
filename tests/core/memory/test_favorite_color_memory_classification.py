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
    assert favorites[0].metadata["retention_scope"] == "user_profile"
    assert favorites[0].metadata["semantic_class"] == "preference"
    assert not any(s.metadata.get("semantic_class") == "race" for s in signals)


def test_liking_black_without_favorite_claim_does_not_invent_favorite() -> None:
    signals = classify_explicit_user_memory("I love the color black.")
    assert not any(s.metadata.get("attribute") == "favorite_color" for s in signals)
