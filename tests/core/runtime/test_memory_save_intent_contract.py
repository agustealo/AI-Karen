"""CORTEX may request a governed memory write, never authorize or execute it."""
from ai_karen_engine.core.cortex.executive import CortexExecutionDecider


def test_explicit_memory_save_language_is_general_and_bounded():
    yes = (
        "Store my place of birth for later",
        "Remember that",
        "Save my favorite color",
        "Please remember this",
        "remember what I just said",
        "Save the preference in memory",
    )
    for text in yes:
        assert CortexExecutionDecider._explicit_memory_save_request(text), text


def test_memory_save_intent_does_not_hijack_recall_or_unrelated_text():
    no = (
        "What do you remember about me?",
        "Where was I born?",
        "Please remember to call me tomorrow",
        "How much RAM do I have left?",
        "They told me to remember that",
    )
    for text in no:
        assert not CortexExecutionDecider._explicit_memory_save_request(text), text
