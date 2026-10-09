"""Personal recall requests must survive degraded intent classification."""

from ai_karen_engine.core.memory.signals.semantic_classifier import (
    is_personal_memory_recall_query,
)


def test_explicit_personal_recall_queries():
    for query in (
        "Where am I from?",
        "Where was I born?",
        "Where did I grow up?",
        "Where do I live?",
        "Where do I work?",
        "What is my favorite color?",
        "What are my goals?",
        "What do you remember about me?",
        "Do you remember my birthplace?",
    ):
        assert is_personal_memory_recall_query(query), query


def test_personal_recall_does_not_claim_general_or_new_facts():
    for query in (
        "I was born in Jamaica",
        "What is the weather in Detroit?",
        "Where is Jamaica?",
        "Remember my birthplace",
        "What is 2 + 2?",
        "Where should I travel?",
        "Where are we meeting?",
    ):
        assert not is_personal_memory_recall_query(query), query


def test_cortex_reuses_canonical_personal_recall_signal():
    from ai_karen_engine.core.cortex.executive import CortexExecutionDecider

    assert CortexExecutionDecider._personal_recall_query("Where was I born?")
    assert not CortexExecutionDecider._personal_recall_query("Where is Jamaica?")
    assert not CortexExecutionDecider._personal_recall_query(
        "Please remember to call me tomorrow"
    )
