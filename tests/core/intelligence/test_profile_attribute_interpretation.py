"""Canonical profile intent attribute remains stable without model inference."""

import pytest

from ai_karen_engine.core.intelligence.profile_attribute import requested_profile_attribute
from ai_karen_engine.platform.memory.postgres.profile_retriever import (
    PostgresProfileRecallRetriever,
)


@pytest.mark.parametrize(
    ("question", "attribute"),
    [
        ("Where was I born?", "birthplace"),
        ("Tell me my birthplace", "birthplace"),
        ("Where do I live?", "residence_location"),
        ("Where am I based?", "residence_location"),
        ("Where am I from?", "origin_location"),
        ("Where did I say I'm from?", "origin_location"),
        ("Where do I work?", "work_location"),
        ("Where am I right now?", "current_location"),
        ("What is my name?", "preferred_name"),
        ("Where was I born and where do I live?", None),
        ("Where is the nearest pharmacy?", None),
        ("Tell me about my background", None),
    ],
)
def test_requested_profile_attribute_and_retriever_share_one_interpretation(question, attribute):
    assert requested_profile_attribute(question) == attribute
    assert PostgresProfileRecallRetriever._preferred_attribute(question) == attribute
