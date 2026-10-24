"""Combined identity assertions remain factual and use the governed write gate."""
from ai_karen_engine.core.memory.signals.semantic_classifier import (
    classify_explicit_user_memory, is_explicit_memory_save_request,
)


def test_combined_name_and_save_request_is_not_a_long_name():
    utterance = "My name is Zeus remember it!"
    signals = classify_explicit_user_memory(utterance)
    names = [s for s in signals if s.metadata.get("attribute") == "preferred_name"]
    assert len(names) == 1
    assert names[0].metadata["normalized_value"] == "Zeus"
    assert is_explicit_memory_save_request(utterance)


def test_identity_statement_alone_does_not_force_a_save_receipt():
    assert not is_explicit_memory_save_request("My name is Zeus.")
    assert not is_explicit_memory_save_request("My name is Zeus remember something else")
