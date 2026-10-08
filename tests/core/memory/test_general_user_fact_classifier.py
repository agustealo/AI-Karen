from __future__ import annotations

from ai_karen_engine.core.memory.signals.general_fact_classifier import (
    classify_general_user_facts,
)
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


def test_relationship_fact_is_typed_and_durable_candidate() -> None:
    signal = _one("My wife is Ana.", "profile_fact")

    assert signal.metadata["category"] == "relationship"
    assert signal.metadata["attribute"] == "relationship.wife"
    assert signal.metadata["normalized_value"] == "Ana"
    assert signal.metadata["semantic_class"] == "relationship"


def test_occupation_fact_is_typed() -> None:
    signal = _one("I am a licensed electrician.", "profile_fact")

    assert signal.metadata["category"] == "work"
    assert signal.metadata["attribute"] == "occupation"
    assert signal.metadata["normalized_value"] == "licensed electrician"


def test_employer_fact_is_typed() -> None:
    signal = _one("I work at Ford.", "profile_fact")

    assert signal.metadata["category"] == "work"
    assert signal.metadata["attribute"] == "employer"
    assert signal.metadata["normalized_value"] == "Ford"


def test_skill_fact_uses_multi_value_key() -> None:
    signal = _one("I'm skilled in WordPress development.", "profile_fact")

    assert signal.metadata["category"] == "skill"
    assert str(signal.metadata["attribute"]).startswith("skill.")
    assert signal.metadata["normalized_value"] == "WordPress development"


def test_routine_fact_is_typed() -> None:
    signal = _one("I usually work out in the morning.", "profile_fact")

    assert signal.metadata["category"] == "routine"
    assert signal.metadata["normalized_value"] == "work out in the morning"
    assert signal.metadata["frequency_word"] == "usually"


def test_market_interest_is_interest_not_financial_account_fact() -> None:
    signal = _one("I follow NVDA.", "profile_fact")

    assert signal.metadata["category"] == "interest"
    assert signal.metadata["normalized_value"] == "NVDA"
    assert signal.metadata["interest_mode"] == "tracked"


def test_active_project_is_profile_fact() -> None:
    signal = _one("I'm building an AI assistant for contractors.", "profile_fact")

    assert signal.metadata["category"] == "project"
    assert signal.metadata["lifecycle_state"] == "active"


def test_travel_plan_uses_existing_prospective_event_contract() -> None:
    signal = _one("I'm planning a trip to Jamaica next month.", "prospective_event")

    assert signal.metadata["event_type"] == "travel"
    assert signal.metadata["attribute"] == "travel_plan"
    assert "Jamaica next month" in signal.metadata["temporal_text"]


def test_temporary_self_description_is_not_promoted_to_occupation() -> None:
    signals = classify_general_user_facts("I'm a little tired.")

    assert not any(
        signal.metadata.get("attribute") == "occupation"
        for signal in signals
    )


def test_relationship_requires_person_like_name() -> None:
    signals = classify_general_user_facts("My friend is awesome.")

    assert not any(
        signal.metadata.get("category") == "relationship"
        for signal in signals
    )


def test_location_facts_are_distinct_and_durable_candidates() -> None:
    from ai_karen_engine.core.memory.signals.general_fact_classifier import (
        classify_general_user_facts,
    )

    facts = classify_general_user_facts(
        "I live in NYC, born in Jamaica. I'm currently in Detroit. I'm from Jamaica."
    )
    location = {
        item.metadata.get("attribute"): item.metadata.get("normalized_value")
        for item in facts
        if item.metadata.get("category") == "location"
    }
    assert location == {
        "residence_location": "NYC",
        "birthplace": "Jamaica",
        "current_location": "Detroit",
        "origin_location": "Jamaica",
    }
    assert all(item.signal_type == "profile_fact" for item in facts if item.metadata.get("category") == "location")


def test_location_language_does_not_promote_weather_queries_to_profile_facts() -> None:
    from ai_karen_engine.core.memory.signals.general_fact_classifier import (
        classify_general_user_facts,
    )

    assert not [
        item for item in classify_general_user_facts("What's the weather in Detroit?")
        if item.metadata.get("category") == "location"
    ]


def test_personal_recall_queries_include_location_and_correction() -> None:
    from ai_karen_engine.core.cortex.executive import CortexExecutionDecider

    for query in (
        "Where am I from?",
        "Where was I born?",
        "Where do I live?",
        "Where am I currently?",
        "I already told you where I'm from",
    ):
        assert CortexExecutionDecider._personal_recall_query(query)

    assert not CortexExecutionDecider._personal_recall_query("Weather in Detroit")


def test_postgres_profile_retriever_recognizes_origin_queries() -> None:
    from ai_karen_engine.platform.memory.postgres.profile_retriever import (
        PostgresProfileRecallRetriever,
    )

    assert PostgresProfileRecallRetriever._looks_like_profile_query("Where am I from?")
    assert PostgresProfileRecallRetriever._looks_like_profile_query("Where do I live?")
    assert not PostgresProfileRecallRetriever._looks_like_profile_query("Weather in Detroit")


def test_conjunction_separates_origin_from_residence_without_splitting_place_name() -> None:
    facts = classify_general_user_facts(
        "I live in NYC and I'm from Jamaica. I was born in Trinidad and Tobago."
    )
    locations = {
        fact.metadata.get("attribute"): fact.metadata.get("normalized_value")
        for fact in facts
        if fact.metadata.get("category") == "location"
    }
    assert locations["residence_location"] == "NYC"
    assert locations["origin_location"] == "Jamaica"
    assert locations["birthplace"] == "Trinidad and Tobago"
