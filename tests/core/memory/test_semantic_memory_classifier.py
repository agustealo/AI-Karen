from __future__ import annotations

from ai_karen_engine.core.memory.signals.semantic_classifier import (
    classify_explicit_user_memory,
)


def _one(text: str, signal_type: str):
    matches = [
        signal
        for signal in classify_explicit_user_memory(text)
        if signal.signal_type == signal_type
    ]
    assert len(matches) == 1
    return matches[0]


def test_explicit_name_becomes_identity_fact() -> None:
    signal = _one("My name is Orlando.", "identity_fact")

    assert signal.confidence >= 0.95
    assert signal.metadata["category"] == "identity"
    assert signal.metadata["attribute"] == "preferred_name"
    assert signal.metadata["normalized_value"] == "Orlando"
    assert signal.metadata["retention_scope"] == "user_profile"
    assert signal.metadata["explicit_user_statement"] is True


def test_favorite_color_becomes_long_term_preference() -> None:
    signal = _one("My favorite color is green.", "preference")

    assert signal.metadata["category"] == "preference"
    assert signal.metadata["attribute"] == "favorite_color"
    assert signal.metadata["normalized_value"] == "green"
    assert signal.metadata["stability"] == "long_term"


def test_favorite_color_correction_is_classified_as_same_preference_key() -> None:
    signal = _one("Actually orange is my favorite color now.", "preference")

    assert signal.metadata["attribute"] == "favorite_color"
    assert signal.metadata["normalized_value"] == "orange"


def test_gym_goal_becomes_explicit_goal_not_generic_preference() -> None:
    signals = classify_explicit_user_memory("I'm trying to work out four days a week.")

    goals = [signal for signal in signals if signal.signal_type == "goal"]
    assert len(goals) == 1
    assert goals[0].metadata["goal_type"] == "explicit"
    assert goals[0].metadata["description"] == "work out four days a week"
    assert goals[0].metadata["lifecycle_state"] == "active"


def test_job_interview_becomes_prospective_event() -> None:
    signal = _one(
        "I have a job interview with Ford Friday at 2 PM.",
        "prospective_event",
    )

    assert signal.metadata["event_type"] == "job_interview"
    assert signal.metadata["lifecycle_state"] == "dormant"
    assert "with Ford Friday at 2 PM" in signal.metadata["temporal_text"]


def test_interview_is_not_duplicated_as_goal() -> None:
    signals = classify_explicit_user_memory(
        "I have a job interview with Ford Friday at 2 PM."
    )

    assert [signal.signal_type for signal in signals] == ["prospective_event"]


def test_unrelated_text_does_not_create_explicit_user_state() -> None:
    assert classify_explicit_user_memory("Explain how TCP congestion control works.") == []
