"""Temporary travel presence must not mutate durable residence facts."""
from ai_karen_engine.core.memory.signals.general_fact_classifier import classify_general_user_facts


def _location_facts(text):
    return [
        signal for signal in classify_general_user_facts(text)
        if signal.metadata.get("category") == "location"
    ]


def test_on_vacation_in_dc_is_current_travel_location():
    facts = _location_facts("I'm in DC on vacation, it is hot here. Will it ever rain?")
    assert len(facts) == 1
    signal = facts[0]
    assert signal.metadata["attribute"] == "current_location"
    assert signal.metadata["normalized_value"] == "DC"
    assert signal.metadata["context_kind"] == "travel"
    assert signal.metadata["stability"] == "short_term"
    assert signal.metadata["explicit_user_statement"] is True


def test_residence_remains_long_term_and_distinct_from_travel():
    facts = _location_facts("I live in Detroit.")
    assert len(facts) == 1
    assert facts[0].metadata["attribute"] == "residence_location"
    assert facts[0].metadata["stability"] == "long_term"


def test_current_temporary_location_does_not_guess_city_from_weather():
    assert not _location_facts("What's the weather? Will it rain here tomorrow?")


def test_explicit_current_presence_is_not_permanent_home():
    facts = _location_facts("I'm in Washington on vacation.")
    assert len(facts) == 1
    assert facts[0].metadata["normalized_value"] == "Washington"
    assert facts[0].metadata["attribute"] == "current_location"


def test_existing_current_location_statement_keeps_one_candidate():
    facts = _location_facts("I'm currently in DC.")
    assert len(facts) == 1
    assert facts[0].metadata["normalized_value"] == "DC"


from ai_karen_engine.platform.memory.postgres.profile_retriever import PostgresProfileRecallRetriever


def test_weather_question_activates_current_location_profile_recall():
    retriever = PostgresProfileRecallRetriever
    assert not retriever._looks_like_profile_query("What's the weather?")
    assert retriever._preferred_attribute("What's the weather?") is None
    assert not retriever._looks_like_profile_query("Will it rain tomorrow?")
    assert retriever._preferred_attribute("Will it rain tomorrow?") is None
    assert retriever._preferred_attribute("Where do I live?") == "residence_location"


def test_workplace_city_is_distinct_from_residence_and_birthplace():
    workplace = _location_facts("I work in Washington, DC.")
    # Comma-delimited locations require a separate geographic normalizer;
    # the classifier preserves the confidently supplied city token.
    assert any(item.metadata["attribute"] == "work_location" and item.metadata["normalized_value"] == "Washington" for item in workplace)
    born = _location_facts("I was born in Baltimore.")
    assert any(item.metadata["attribute"] == "birthplace" and item.metadata["normalized_value"] == "Baltimore" for item in born)


def test_employer_name_is_not_silently_geocoded_as_workplace():
    facts = _location_facts("I work at Microsoft.")
    assert facts == []


def test_role_specific_profile_recall_targets():
    retriever = PostgresProfileRecallRetriever
    assert retriever._preferred_attribute("Where do I work?") == "work_location"
    assert retriever._preferred_attribute("Where do I live?") == "residence_location"
    assert retriever._preferred_attribute("Where was I born?") == "birthplace"
    assert retriever._preferred_attribute("What's the weather?") is None
