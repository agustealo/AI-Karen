"""Personal recall searches must be invariant to semantically irrelevant emphasis."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext, ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.evidence_resolver import RuntimeEvidenceResolver


@pytest.mark.parametrize(
    ("plain", "emphatic"),
    [
        ("What is my name?", "What is my fucking name?"),
        ("Whats my name?", "Whats my fucking name?"),
        ("Where am I from?", "Where the fuck am I from?"),
        ("Where was I born?", "Where the hell was I born?"),
    ],
)
def test_recall_search_query_is_invariant_to_emphasis(plain, emphatic):
    ctx = ChatExecutionContext(
        user_id="user", tenant_id="tenant", session_id="session",
        conversation_id="conversation", request_id="request", correlation_id="correlation",
    )
    requirement = SimpleNamespace(metadata={})
    def build(utterance):
        return ChatExecutionRequest(messages=[{"role": "user", "content": utterance}], context=ctx)

    assert RuntimeEvidenceResolver._memory_retrieval_query(
        build(plain), requirement
    ) == RuntimeEvidenceResolver._memory_retrieval_query(build(emphatic), requirement)


def test_non_personal_query_and_original_utterance_are_unchanged():
    utterance = "Explain the fucking difference between a stack and a queue."
    ctx = ChatExecutionContext(
        user_id="user", tenant_id="tenant", session_id="session",
        conversation_id="conversation", request_id="request", correlation_id="correlation",
    )
    request = ChatExecutionRequest(messages=[{"role": "user", "content": utterance}], context=ctx)
    requirement = SimpleNamespace(metadata={})
    assert RuntimeEvidenceResolver._memory_retrieval_query(request, requirement) == utterance
    assert request.messages[-1]["content"] == utterance


def test_explicit_retrieval_query_remains_authoritative_for_unrelated_requests():
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "My name is Zeus"}],
        context=ChatExecutionContext(
            user_id="user", tenant_id="tenant", session_id="session",
            conversation_id="conversation", request_id="request", correlation_id="correlation",
        ),
    )
    requirement = SimpleNamespace(metadata={"retrieval_query": "project status"})
    assert RuntimeEvidenceResolver._memory_retrieval_query(request, requirement) == "project status"
