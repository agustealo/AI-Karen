"""Prompt and memory-signal contracts for acknowledging user volunteered facts."""

from ai_karen_engine.core.memory.signals.general_fact_classifier import (
    classify_general_user_facts,
)
from ai_karen_engine.core.runtime.prompt.prompt_assembler import (
    _EVIDENCE_FIRST_INSTRUCTION,
)


def test_volunteered_origin_is_classified_without_changing_relation():
    signals = classify_general_user_facts("I am from Jamaica")
    assert any(
        signal.metadata.get("attribute") == "origin_location"
        and signal.metadata.get("normalized_value") == "Jamaica"
        for signal in signals
    )


def test_canonical_prompt_requires_second_person_acknowledgment():
    prompt = _EVIDENCE_FIRST_INSTRUCTION.lower()
    assert "acknowledge that information" in prompt
    assert "second person" in prompt
    assert "without merely repeating the first-person statement" in prompt
    assert "does not establish birthplace, residence, or current location" in prompt
    assert "without a confirmed" in prompt
