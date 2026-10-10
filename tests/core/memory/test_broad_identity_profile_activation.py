"""Broad user identity requests activate governed profile recall, not model guessing."""

from ai_karen_engine.platform.memory.postgres.profile_retriever import PostgresProfileRecallRetriever


def test_broad_identity_request_activates_profile_candidate_source():
    assert PostgresProfileRecallRetriever._looks_like_profile_query("Who am I?")
    assert PostgresProfileRecallRetriever._looks_like_profile_query("who am i")
    assert PostgresProfileRecallRetriever._preferred_attribute("Who am I?") is None


def test_non_profile_request_does_not_activate_profile_candidate_source():
    assert not PostgresProfileRecallRetriever._looks_like_profile_query(
        "Explain how the solar system formed."
    )
