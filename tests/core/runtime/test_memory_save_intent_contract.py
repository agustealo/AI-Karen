"""CORTEX may request a governed memory write, never authorize or execute it."""
from ai_karen_engine.core.memory.signals.semantic_classifier import is_explicit_memory_save_request


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
        assert is_explicit_memory_save_request(text), text


def test_memory_save_intent_does_not_hijack_recall_or_unrelated_text():
    no = (
        "What do you remember about me?",
        "Where was I born?",
        "Please remember to call me tomorrow",
        "How much RAM do I have left?",
        "They told me to remember that",
    )
    for text in no:
        assert not is_explicit_memory_save_request(text), text


def test_explicit_reference_resolves_only_authorized_user_profile_facts():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
    from ai_karen_engine.core.runtime.chat_runtime_contract import (
        ChatExecutionContext, ChatExecutionRequest,
    )
    ctx = ChatExecutionContext(
        user_id="u", tenant_id="tenant", session_id="s",
        conversation_id="c", request_id="r", correlation_id="r",
    )
    req = ChatExecutionRequest(
        messages=[
            {"role": "user", "content": "My place of birth is Jamaica."},
            {"role": "assistant", "content": "Understood."},
            {"role": "user", "content": "Store my place of birth for later"},
        ],
        context=ctx,
    )
    resolved = ChatRuntime._resolve_explicit_memory_reference(
        req, req.messages[-1]["content"]
    )
    assert "Jamaica" in resolved
    assert "birth" in resolved.casefold()
    assert req.messages[-1]["content"] == "Store my place of birth for later"


def test_unresolved_and_non_save_requests_are_not_rewritten():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
    from ai_karen_engine.core.runtime.chat_runtime_contract import (
        ChatExecutionContext, ChatExecutionRequest,
    )
    ctx = ChatExecutionContext(
        user_id="u", tenant_id="tenant", session_id="s",
        conversation_id="c", request_id="r", correlation_id="r",
    )
    req = ChatExecutionRequest(
        messages=[
            {"role": "assistant", "content": "My birthplace is Jamaica."},
            {"role": "user", "content": "Store my place of birth for later"},
        ],
        context=ctx,
    )
    assert ChatRuntime._resolve_explicit_memory_reference(
        req, req.messages[-1]["content"]
    ) == "Store my place of birth for later"
    assert ChatRuntime._resolve_explicit_memory_reference(
        req, "Where was I born?"
    ) == "Where was I born?"
