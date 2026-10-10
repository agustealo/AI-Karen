"""Canonical expression output rejects assistant planning narration."""
from ai_karen_engine.core.errors.response_validation import validate_response_text


def test_rejects_exposed_model_planning_narration():
    examples = [
        'Alright, the user just said, "My name is Zeus." That is pretty funny.',
        "The user is asking about their identity in this context.",
        "The user wants me to explain something else instead.",
        "I should explain how Zeus fits into mythology.",
        "When asked about the user in this context, it's important to recognize identity.",
    ]
    for text in examples:
        assert not validate_response_text(text), text


def test_legitimate_conversation_is_not_blocked():
    examples = [
        "Got it, Zeus. I'll call you Zeus.",
        "Your name is Zeus.",
        "I'm doing well, Zeus. How's your day going?",
        "The user interface needs a different layout.",
        "I should be able to help you with that.",
    ]
    for text in examples:
        assert validate_response_text(text), text
