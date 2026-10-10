"""Regression contract for canonical name, greeting and reply presentation prompt."""
from ai_karen_engine.core.runtime.prompt.prompt_assembler import (
    _EVIDENCE_FIRST_INSTRUCTION,
)


def test_name_utterances_are_not_mythology_or_meta_commentary():
    prompt = _EVIDENCE_FIRST_INSTRUCTION.lower()
    for requirement in (
        "user states their name",
        "when asked for their name",
        "authorized evidence",
        "explicit requests to be addressed by",
        "subsequent corrections",
        "mythological trivia",
    ):
        assert requirement in prompt


def test_greeting_and_visible_answer_hygiene_is_canonical():
    prompt = _EVIDENCE_FIRST_INSTRUCTION.lower()
    assert "greetings conversationally" in prompt
    assert "speculating about the user's motives" in prompt
    assert "never private planning, internal monologue" in prompt
    assert "this instruction does not authorize a tool" in prompt
