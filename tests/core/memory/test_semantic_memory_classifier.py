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


def test_explicit_goal_abandonment_becomes_lifecycle_evidence() -> None:
    signal = _one(
        "I stopped trying to work out four days a week.",
        "goal_transition",
    )

    assert signal.metadata["target_state"] == "abandoned"
    assert signal.metadata["target_description"] == "work out four days a week"


def test_cancelled_interview_becomes_prospective_lifecycle_evidence() -> None:
    signal = _one(
        "My job interview was cancelled.",
        "prospective_transition",
    )

    assert signal.metadata["event_type"] == "job_interview"
    assert signal.metadata["target_state"] == "cancelled"


def test_job_offer_completes_current_interview_without_creating_new_interview() -> None:
    signals = classify_explicit_user_memory("They offered me the job.")

    transitions = [
        signal for signal in signals if signal.signal_type == "prospective_transition"
    ]
    assert len(transitions) == 1
    assert transitions[0].metadata["target_state"] == "completed"
    assert transitions[0].metadata["outcome"] == "job_offer"
    assert not any(signal.signal_type == "prospective_event" for signal in signals)


def test_unfinished_work_becomes_open_loop() -> None:
    signal = _one(
        "I still need to send the client the revised estimate.",
        "open_loop",
    )

    assert signal.metadata["loop_type"] == "unfinished_work"
    assert signal.metadata["description"] == "send the client the revised estimate"
    assert signal.metadata["lifecycle_state"] == "open"


def test_completed_unfinished_work_becomes_open_loop_transition() -> None:
    signal = _one(
        "I finished sending the client the revised estimate.",
        "open_loop_transition",
    )

    assert signal.metadata["target_state"] == "completed"
    assert signal.metadata["target_description"] == "sending the client the revised estimate"


def test_unrelated_text_does_not_create_explicit_user_state() -> None:
    assert classify_explicit_user_memory("Explain how TCP congestion control works.") == []


def test_colloquial_first_person_identity_is_session_evidence_not_birthplace() -> None:
    signals = classify_explicit_user_memory("I Jamaican, where am I from?")
    descriptions = [
        item for item in signals
        if item.metadata.get("attribute") == "self_description"
    ]
    assert len(descriptions) == 1
    assert descriptions[0].metadata["normalized_value"] == "Jamaican"
    assert descriptions[0].metadata["retention_scope"] == "session"
    assert descriptions[0].metadata["not_verified_birthplace"] is True
    assert not any(
        item.metadata.get("attribute") in {"birthplace", "origin_location"}
        for item in signals
    )


def test_explicit_origin_remains_distinct_from_self_description() -> None:
    signals = classify_explicit_user_memory("I'm from Jamaica.")
    assert any(
        item.metadata.get("attribute") == "origin_location"
        and item.metadata.get("normalized_value") == "Jamaica"
        for item in signals
    )
    assert not any(item.metadata.get("attribute") == "birthplace" for item in signals)


def test_short_self_description_does_not_infer_identity_from_generic_question() -> None:
    signals = classify_explicit_user_memory("Where am I from?")
    assert not any(item.metadata.get("attribute") == "self_description" for item in signals)
