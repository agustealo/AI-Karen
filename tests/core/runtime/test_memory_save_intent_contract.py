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


def test_memory_receipt_is_only_successful_after_verified_persistence():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime

    receipt = ChatRuntime._memory_write_receipt_text(
        {"status": "completed", "persisted": 2},
        {"memory_persistence_status": "persisted"},
    )
    assert receipt == "Saved 2 memory facts for future conversations."

    for result, meta in [
        ({"status": "completed", "persisted": 0}, {"memory_persistence_status": "no_candidate"}),
        ({"status": "failed", "persisted": 0}, {"memory_persistence_status": "failed"}),
        ({"status": "rejected", "reason": "memory_write_not_authorized", "persisted": 0},
         {"memory_persistence_status": "denied_by_policy"}),
        ({"status": "completed", "persisted": 2}, {"memory_persistence_status": "failed"}),
    ]:
        acknowledgement = ChatRuntime._memory_write_receipt_text(result, meta)
        assert "Saved" not in acknowledgement
        assert "couldn't" in acknowledgement


def test_save_intent_is_not_recognized_from_assistant_messages():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext, ChatExecutionRequest

    runtime = ChatRuntime.__new__(ChatRuntime)
    request = ChatExecutionRequest(
        context=ChatExecutionContext(
            user_id="user", tenant_id="tenant", session_id="session",
            conversation_id="conversation", request_id="request",
            correlation_id="correlation",
        ),
        messages=[
            {"role": "assistant", "content": "Store my name"},
            {"role": "user", "content": "How are you?"},
        ],
    )
    assert not runtime._is_explicit_save_turn(request)
    request.messages[-1]["content"] = "Store my name"
    assert runtime._is_explicit_save_turn(request)

def test_targeted_save_request_never_falls_back_to_unrelated_recent_fact():
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
            {"role": "user", "content": "I work at Acme Labs."},
            {"role": "assistant", "content": "Got it."},
            {"role": "user", "content": "I live in Detroit."},
            {"role": "assistant", "content": "Understood."},
            {"role": "user", "content": "Remember my employer"},
        ],
        context=ctx,
    )

    resolved = ChatRuntime._resolve_explicit_memory_reference(
        req, req.messages[-1]["content"]
    )
    assert "Acme Labs" in resolved
    assert "Detroit" not in resolved


def test_unknown_target_does_not_save_an_unrelated_profile_fact():
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
            {"role": "user", "content": "I live in Detroit."},
            {"role": "assistant", "content": "Understood."},
            {"role": "user", "content": "Remember my shoe size"},
        ],
        context=ctx,
    )

    assert ChatRuntime._resolve_explicit_memory_reference(
        req, req.messages[-1]["content"]
    ) == "Remember my shoe size"


def test_deictic_save_request_can_use_latest_eligible_profile_fact():
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
            {"role": "user", "content": "I work at Acme Labs."},
            {"role": "assistant", "content": "Got it."},
            {"role": "user", "content": "Remember that"},
        ],
        context=ctx,
    )

    resolved = ChatRuntime._resolve_explicit_memory_reference(
        req, req.messages[-1]["content"]
    )
    assert "Acme Labs" in resolved



def test_related_location_facts_resolve_independently_without_cross_selection():
    """Explicit targets must never inherit a neighboring location attribute."""
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
    from ai_karen_engine.core.runtime.chat_runtime_contract import (
        ChatExecutionContext,
        ChatExecutionRequest,
    )

    context = ChatExecutionContext(
        user_id="user",
        tenant_id="tenant",
        session_id="session",
        conversation_id="conversation",
        request_id="request",
        correlation_id="correlation",
    )
    history = [
        {"role": "user", "content": "I was born in Kingston."},
        {"role": "assistant", "content": "Noted."},
        {"role": "user", "content": "I grew up in Toronto."},
        {"role": "assistant", "content": "Noted."},
        {"role": "user", "content": "I live in Detroit."},
        {"role": "assistant", "content": "Noted."},
    ]
    scenarios = (
        ("Store my birthplace", "Kingston", ("Toronto", "Detroit")),
        ("Store my upbringing location", "Toronto", ("Kingston", "Detroit")),
        ("Store my residence location", "Detroit", ("Kingston", "Toronto")),
    )
    for command, expected, excluded in scenarios:
        request = ChatExecutionRequest(
            messages=[*history, {"role": "user", "content": command}],
            context=context,
        )
        resolved = ChatRuntime._resolve_explicit_memory_reference(request, command)
        assert expected in resolved, command
        assert all(place not in resolved for place in excluded), command
        assert request.messages[-1]["content"] == command


def test_targeted_location_save_never_promotes_temporary_presence_to_residence():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
    from ai_karen_engine.core.runtime.chat_runtime_contract import (
        ChatExecutionContext,
        ChatExecutionRequest,
    )

    request = ChatExecutionRequest(
        context=ChatExecutionContext(
            user_id="user",
            tenant_id="tenant",
            session_id="session",
            conversation_id="conversation",
            request_id="request",
            correlation_id="correlation",
        ),
        messages=[
            {"role": "user", "content": "I'm in Washington on vacation."},
            {"role": "assistant", "content": "Enjoy your trip."},
            {"role": "user", "content": "Store my residence location"},
        ],
    )
    assert ChatRuntime._resolve_explicit_memory_reference(
        request, request.messages[-1]["content"]
    ) == "Store my residence location"
